"""Read-only YOLO audit; writes reports/previews separately, never edits labels."""

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import yaml

ROOT = Path(__file__).resolve().parents[1] / "datasets" / "xbot_head"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(dataset, output):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    errors, warnings, records = [], [], []
    hashes = {}
    summaries = {}
    for split in ("train", "val"):
        images = sorted(p for p in (dataset/"images"/split).iterdir()
                        if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
        labels = sorted((dataset/"labels"/split).glob("*.txt"))
        counts = Counter(p.stem.casefold() for p in images)
        for stem, count in counts.items():
            if count > 1:
                errors.append(f"{split}: duplicate image stem {stem}")
        image_stems = {p.stem for p in images}
        for label in labels:
            hashes[label] = digest(label)
            if label.stem not in image_stems:
                errors.append(f"Orphan label: {label.relative_to(dataset)}")
        positives = negatives = boxes_count = 0
        for index, path in enumerate(images, 1):
            hashes[path] = digest(path)
            relative = str(path.relative_to(dataset))
            label = dataset/"labels"/split/(path.stem+".txt")
            boxes = []
            if not label.is_file():
                errors.append(f"Missing label: {relative}")
                text = None
            else:
                try:
                    text = label.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError) as error:
                    errors.append(f"Unreadable label {label.name}: {type(error).__name__}")
                    text = None
            if text is not None:
                if not text.strip():
                    negatives += 1
                else:
                    positives += 1
                for line_number, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    prefix = f"{split}/{label.name}:{line_number}"
                    fields = line.split()
                    try:
                        if len(fields) != 5 or fields[0] != "0":
                            raise ValueError("expected class ID 0 and exactly four box coordinates")
                        cx, cy, w, h = map(float, fields[1:])
                        if not all(math.isfinite(v) for v in (cx,cy,w,h)):
                            raise ValueError("non-finite coordinate")
                        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1):
                            raise ValueError("coordinates outside normalized range or nonpositive size")
                        if cx-w/2 < -1e-6 or cy-h/2 < -1e-6 or cx+w/2 > 1+1e-6 or cy+h/2 > 1+1e-6:
                            raise ValueError("box edges extend outside image")
                        box = [cx, cy, w, h]
                        if box in boxes:
                            warnings.append(prefix+": duplicate bounding box")
                        boxes.append(box)
                    except ValueError as error:
                        errors.append(prefix+": "+str(error))
            boxes_count += len(boxes)
            try:
                with Image.open(path) as image:
                    image.load()
                    rgb = image.convert("RGB")
                    width, height = rgb.size
                    pixel_hash = hashlib.sha256(str(rgb.size).encode()+rgb.tobytes()).hexdigest()
                    thumb = np.asarray(rgb.convert("L").resize((256, 256)), dtype=np.float32)
                    small = np.asarray(rgb.convert("L").resize((9, 8)), dtype=np.int16)
                    dhash = np.packbits(small[:,1:] > small[:,:-1]).tobytes().hex()
                for box in boxes:
                    if box[2]*width < 4 or box[3]*height < 4:
                        warnings.append(relative+": box smaller than 4 pixels on at least one axis")
                records.append(dict(id=("T" if split == "train" else "V")+f"{index:03d}",
                                    path=relative, split=split, width=width, height=height, boxes=boxes,
                                    empty_label=text is not None and not text.strip(),
                                    sha256=hashes[path], pixel_sha256=pixel_hash, dhash=dhash,
                                    run=(re.match(r"^(\d{8}T\d{6}Z_[0-9a-f]{8})_", path.stem) or [None, None])[1],
                                    _thumb=thumb))
            except (OSError, ValueError) as error:
                errors.append(f"Unreadable image {relative}: {type(error).__name__}")
        summaries[split] = dict(images=len(images), labels=len(labels), positives=positives,
                                empty_labels=negatives, valid_boxes=boxes_count)

    exact, near = [], []
    for a, b in itertools.combinations(records, 2):
        if a["pixel_sha256"] == b["pixel_sha256"] or a["sha256"] == b["sha256"]:
            exact.append(dict(a=a["path"], b=b["path"], cross_split=a["split"] != b["split"]))
            continue
        distance = (int(a["dhash"],16)^int(b["dhash"],16)).bit_count()
        mae = float(np.abs(a["_thumb"]-b["_thumb"]).mean())
        if distance <= 6 and mae <= 8:
            near.append(dict(a=a["path"], b=b["path"], cross_split=a["split"] != b["split"],
                             dhash_distance=distance, gray_mae_256=round(mae, 3)))
    near.sort(key=lambda row: (not row["cross_split"], row["gray_mae_256"], row["dhash_distance"]))
    runs = {split: sorted({r["run"] for r in records if r["split"] == split and r["run"]}) for split in ("train", "val")}
    shared_runs = sorted(set(runs["train"]) & set(runs["val"]))
    if shared_runs:
        warnings.append("Capture runs occur in both splits: "+", ".join(shared_runs))
    if any(row["cross_split"] for row in exact):
        warnings.append("Exact duplicate images occur across train/validation")
    if any(row["cross_split"] for row in near):
        warnings.append("Potential near-duplicate train/validation pairs require visual review")
    try:
        config = yaml.safe_load((dataset/"data.yaml").read_text())
        if config.get("names") not in ({0:"xbot_head"}, ["xbot_head"]):
            errors.append("data.yaml must define only class 0 = xbot_head")
        if config.get("train") != "images/train" or config.get("val") != "images/val":
            errors.append("data.yaml split paths do not match exported folders")
        if Path(config.get("path", "")).resolve() != dataset:
            errors.append("data.yaml dataset root does not resolve to this dataset")
    except (OSError, ValueError, AttributeError, yaml.YAMLError) as error:
        errors.append("Cannot validate data.yaml: "+str(error))
    output.mkdir(parents=True, exist_ok=True)
    previews = make_previews(dataset, output, records, near)
    changed = [str(path.relative_to(dataset)) for path, before in hashes.items() if digest(path) != before]
    if changed:
        errors.append("Source files changed during validation: "+", ".join(changed))
    box_widths = [box[2]*r["width"] for r in records for box in r["boxes"]]
    box_heights = [box[3]*r["height"] for r in records for box in r["boxes"]]
    report = dict(splits=summaries, total_images=len(records), total_boxes=len(box_widths),
                  image_resolutions=dict(Counter(f"{r['width']}x{r['height']}" for r in records)),
                  box_width_pixels=dict(min=min(box_widths), max=max(box_widths)) if box_widths else {},
                  box_height_pixels=dict(min=min(box_heights), max=max(box_heights)) if box_heights else {},
                  errors=errors, warnings=warnings, source_files_unchanged=not changed,
                  exact_duplicates=exact, near_duplicates=near, shared_capture_runs=shared_runs,
                  near_duplicate_method="Candidates only: 64-bit dHash distance <=6 AND grayscale 256x256 MAE <=8. Shared backgrounds may overflag distinct poses.",
                  previews=previews, images=[{k:v for k,v in row.items() if not k.startswith("_")} for row in records])
    (output/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("images", "exact_duplicates", "near_duplicates")}, indent=2))
    print("Exact duplicate pairs:", len(exact), "cross-split:", sum(row["cross_split"] for row in exact))
    print("Near-duplicate candidate pairs:", len(near), "cross-split:", sum(row["cross_split"] for row in near))
    return report


def make_previews(dataset, output, records, near):
    tiles, heads = [], []
    lookup = {}
    for row in records:
        with Image.open(dataset/row["path"]) as opened:
            image = opened.convert("RGB")
        draw = ImageDraw.Draw(image)
        for index, (cx,cy,w,h) in enumerate(row["boxes"], 1):
            box = ((cx-w/2)*image.width, (cy-h/2)*image.height,
                   (cx+w/2)*image.width, (cy+h/2)*image.height)
            draw.rectangle(box, outline="#00ff9a", width=3)
            # Separate head crops make loose/misaligned boxes inspectable.
            padx, pady = max(8,w*image.width*.5), max(8,h*image.height*.5)
            head = image.crop((max(0,int(box[0]-padx)), max(0,int(box[1]-pady)),
                               min(image.width,int(box[2]+padx+1)), min(image.height,int(box[3]+pady+1))))
            heads.append((f"{row['id']} head {index}", head))
        label = f"{row['id']} {row['split']} | {len(row['boxes'])} boxes | {image.width}x{image.height}"
        tiles.append((label, image))
        lookup[row["path"]] = (row["id"], image)
    files = []
    def sheets(items, prefix, columns=4, per_page=16):
        for page, start in enumerate(range(0,len(items),per_page),1):
            selected = items[start:start+per_page]
            sheet = Image.new("RGB", (columns*320, math.ceil(len(selected)/columns)*245), "#181e26")
            draw = ImageDraw.Draw(sheet)
            for index,(label,image) in enumerate(selected):
                x,y = index%columns*320,index//columns*245
                preview = ImageOps.contain(image, (308,210))
                sheet.paste(preview,(x+(320-preview.width)//2,y+29+(210-preview.height)//2))
                draw.text((x+8,y+7),label,fill="white")
            name = f"{prefix}_{page:02d}.jpg"
            sheet.save(output/name,quality=94)
            files.append(name)
    sheets(tiles,"annotated")
    sheets(heads,"heads")
    pairs = []
    for pair in [row for row in near if row["cross_split"]][:8]:
        for key in ("a","b"):
            identifier,image = lookup[pair[key]]
            pairs.append((f"{identifier} | dHash {pair['dhash_distance']} MAE {pair['gray_mae_256']}",image))
    sheets(pairs,"near_pairs",columns=2,per_page=8)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    report = audit(dataset, args.output or dataset/"validation")
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
