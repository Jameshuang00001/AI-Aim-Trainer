"""Local annotation persistence and dataset export. No training or network calls."""

import json
import math
from pathlib import Path
import random
import re
import shutil
import uuid

from PIL import Image


def find_images(raw):
    images = sorted(path for path in raw.rglob("*") if path.is_file()
                    and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                    and "preview" not in path.stem.lower()
                    and not any(part.startswith(".") for part in path.relative_to(raw).parts))
    names = [path.stem.casefold() for path in images]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate image stems found. Rename duplicates before annotation to prevent label collisions.")
    return images


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def encode_boxes(boxes, width, height):
    lines = []
    for x1, y1, x2, y2 in boxes:
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("A box is empty or outside the original image.")
        lines.append(f"0 {(x1+x2)/(2*width):.8f} {(y1+y2)/(2*height):.8f} {(x2-x1)/width:.8f} {(y2-y1)/height:.8f}")
    return "\n".join(lines) + ("\n" if lines else "")


def decode_boxes(text, width, height):
    boxes = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != "0":
            raise ValueError("Labels must contain class 0 and four normalized coordinates.")
        cx, cy, w, h = map(float, fields[1:])
        if not all(math.isfinite(v) for v in (cx, cy, w, h)) or min(w, h) <= 0:
            raise ValueError("Invalid YOLO coordinates.")
        x1, y1, x2, y2 = (cx-w/2)*width, (cy-h/2)*height, (cx+w/2)*width, (cy+h/2)*height
        if x1 < -0.001 or y1 < -0.001 or x2 > width+0.001 or y2 > height+0.001:
            raise ValueError("YOLO box extends outside its image.")
        boxes.append((max(0, x1), max(0, y1), min(width, x2), min(height, y2)))
    return boxes


class AnnotationStore:
    def __init__(self, dataset):
        self.dataset = Path(dataset).resolve()
        self.raw = self.dataset / "raw"
        self.images = find_images(self.raw)
        self.work = self.dataset / "annotations"
        self.progress_path = self.work / "progress.json"
        self.progress = json.loads(self.progress_path.read_text()) if self.progress_path.exists() else {}
        if not isinstance(self.progress, dict):
            raise ValueError("Invalid annotation progress file; restore it before continuing.")
        if any(not isinstance(entry, dict) for entry in self.progress.values()):
            raise ValueError("Invalid annotation progress record; restore progress.json before continuing.")

    def key(self, image):
        return str(image.resolve().relative_to(self.raw))

    def label_path(self, image):
        return self.work / (image.stem + ".txt")

    def signature(self, image):
        stat = image.stat()
        return [stat.st_size, stat.st_mtime_ns]

    def reviewed(self, image):
        entry = self.progress.get(self.key(image), {})
        return entry.get("reviewed", False) and entry.get("signature") == self.signature(image) and self.label_path(image).is_file()

    def load(self, image):
        with Image.open(image) as opened:
            size = opened.size
        label = self.label_path(image)
        return decode_boxes(label.read_text(), *size) if label.exists() else []

    def save(self, image, boxes, reviewed=False):
        with Image.open(image) as opened:
            width, height = opened.size
        atomic_text(self.label_path(image), encode_boxes(boxes, width, height))
        self.progress[self.key(image)] = dict(reviewed=reviewed, signature=self.signature(image))
        atomic_text(self.progress_path, json.dumps(self.progress, indent=2))

    def export(self, seed=42):
        if len(self.images) < 2:
            raise ValueError("At least two images are required for train/validation export.")
        if any(not self.reviewed(image) for image in self.images):
            raise ValueError("Review every image before export. Mark true negative images Reviewed with zero boxes.")
        groups = {}
        for image in self.images:
            match = re.match(r"^(\d{8}T\d{6}Z_[0-9a-f]{8})_\d+_", image.stem)
            key = match[1] if match else image.stem
            groups.setdefault(key, []).append(image)
        rng = random.Random(seed)
        target = max(1, min(len(self.images)-1, round(len(self.images)*0.2)))
        warning = ""
        if len(groups) == 1:
            candidates = self.images.copy()
            rng.shuffle(candidates)
            validation = set(candidates[:target])
            warning = "Only one capture run: split by image. Collect independent runs to avoid near-duplicate leakage."
        else:
            keys = list(groups)
            rng.shuffle(keys)
            validation = set()
            # Whole-run selection approximates 20% without leaking adjacent frames.
            while keys:
                key = min(keys, key=lambda k: abs(len(validation)+len(groups[k])-target))
                trial = validation | set(groups[key])
                if len(trial) == len(self.images) or (validation and abs(len(trial)-target) >= abs(len(validation)-target)):
                    break
                validation = trial
                keys.remove(key)
        grouped = len(groups) > 1
        if len(validation) != target:
            candidates = self.images.copy()
            rng.shuffle(candidates)
            validation = set(candidates[:target])
            grouped = False
            warning = "Whole capture runs could not match 80/20; image-level split used. Review near-duplicate leakage before training."
        if len(groups) == 1:
            grouped = False
        stage = self.dataset / (".annotation-export-" + uuid.uuid4().hex)
        parts = [Path(kind) / split for kind in ("images", "labels") for split in ("train", "val")]
        records = []
        moved = []
        backup = self.dataset / "annotation_backups" / uuid.uuid4().hex
        try:
            for part in parts:
                (stage / part).mkdir(parents=True)
                marker = self.dataset / part / ".gitkeep"
                if marker.exists():
                    shutil.copy2(marker, stage / part / ".gitkeep")
            for image in self.images:
                # Validate again before touching any previous export.
                self.load(image)
                split = "val" if image in validation else "train"
                shutil.copy2(image, stage / "images" / split / image.name)
                shutil.copy2(self.label_path(image), stage / "labels" / split / (image.stem + ".txt"))
                records.append(dict(image=self.key(image), split=split))
            for part in parts:
                destination = self.dataset / part
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    (backup / part).parent.mkdir(parents=True, exist_ok=True)
                    destination.rename(backup / part)
                moved.append(part)
                (stage / part).rename(destination)
        except Exception:
            for part in reversed(moved):
                destination = self.dataset / part
                if destination.exists():
                    shutil.rmtree(destination)
                if (backup / part).exists():
                    (backup / part).rename(destination)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        manifest = dict(seed=seed, train=len(self.images)-len(validation), val=len(validation),
                        grouped_by_capture_run=grouped, warning=warning, files=records)
        atomic_text(self.dataset / "split_manifest.json", json.dumps(manifest, indent=2))
        return manifest
