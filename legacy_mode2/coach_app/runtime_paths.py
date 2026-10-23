"""Resource paths for development and a read-only PyInstaller macOS bundle."""
import os
import json
from pathlib import Path
import sys


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def project_root():
    value = os.environ.get("COACH_APP_ROOT")
    return Path(value).expanduser().resolve() if value else resource_root()


def cache_root():
    if getattr(sys, "frozen", False):
        return Path.home() / "Library/Caches/AI-Aim-Trainer"
    return project_root() / "yolo_dev/.cache"


def crop_path():
    local = project_root() / "yolo_dev/capture_region.json"
    if local.is_file():
        return local
    if getattr(sys, "frozen", False):
        return Path.home() / "Library/Application Support/AI-Aim-Trainer/capture_region.json"
    return local


MODEL_RELATIVE = Path('runs/detect/runs/xbot_head/baseline_v1/weights/best.pt')


def resolve_model(explicit=None):
    if explicit is not None:
        candidates = [Path(explicit).expanduser().resolve()]
    elif getattr(sys, 'frozen', False):
        # Standalone Unity's root is often the game's install folder, not source.
        candidates = [resource_root()/MODEL_RELATIVE, project_root()/MODEL_RELATIVE]
    else:
        candidates = [project_root()/MODEL_RELATIVE, resource_root()/MODEL_RELATIVE]
    candidates = list(dict.fromkeys(candidates))
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError('YOLO model missing. Searched exact paths: ' + '; '.join(map(str, candidates)))


def resolve_editor_crop(explicit=None):
    support = Path.home() / 'Library/Application Support/AI-Aim-Trainer'
    candidates = ([Path(explicit).expanduser().resolve()] if explicit is not None else [
        project_root()/'yolo_dev/capture_region.editor.json',
        project_root()/'yolo_dev/capture_region.json',
        support/'capture_region.editor.json', support/'capture_region.json'])
    rejected = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            rejected.append(f'{path} (missing)')
            continue
        try:
            config = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(config, dict) or config.get('app') != 'Unity':
                rejected.append(f'{path} (not a Unity Editor crop)')
                continue
        except (OSError, ValueError) as error:
            rejected.append(f'{path} ({type(error).__name__})')
            continue
        return path
    raise FileNotFoundError('Unity Editor crop unavailable. Checked exact paths: ' + '; '.join(rejected) +
                            '. Configure capture_region.editor.json for Unity; standalone windows need no crop file.')
