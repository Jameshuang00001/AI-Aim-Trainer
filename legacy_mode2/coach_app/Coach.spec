# Build on Apple Silicon with the project's .venv. Never collect .env/credentials.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

root = Path(SPECPATH).parent
os.environ['YOLO_AUTOINSTALL'] = 'False'
weights = root / 'runs/detect/runs/xbot_head/baseline_v1/weights/best.pt'
if not weights.is_file():
    raise RuntimeError('The local trained XBot head model is required')

hidden = collect_submodules('ultralytics') + [
    'keyring.backends.macOS', 'AppKit', 'Quartz', 'Foundation', 'objc',
    'yolo_dev.live_detect', 'yolo_dev.capture_unity', 'coach_app.diagnose_accessibility',
]
a = Analysis([str(root / 'coach_app/packaging_entry.py')], pathex=[str(root)],
    # torchvision 0.29 uses dynamically loaded _C_stable.so/image_stable.so;
    # ordinary import analysis does not discover these native NMS libraries.
    binaries=collect_dynamic_libs('torchvision', search_patterns=['*.so', '*.dylib']),
    datas=[(str(weights), 'runs/detect/runs/xbot_head/baseline_v1/weights')]
        + collect_data_files('ultralytics'), hiddenimports=hidden,
    excludes=['pytest', 'IPython', 'tensorboard', 'tensorflow', 'jupyter', 'notebook'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Coach', console=False,
    argv_emulation=False, target_arch='arm64',
    codesign_identity=os.environ.get('COACH_CODESIGN_IDENTITY') or None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Coach')
app = BUNDLE(coll, name='Coach.app', bundle_identifier='com.ai-aim-trainer.coach',
    info_plist={'CFBundleName': 'Coach', 'CFBundleDisplayName': 'AI Aim Trainer Coach',
        'CFBundleShortVersionString': '1.0.0', 'CFBundleVersion': '1',
        'LSUIElement': True, 'NSHighResolutionCapable': True,
        'NSScreenCaptureUsageDescription': 'Detect XBot heads in your own Unity aim trainer when Mode 2 is enabled.'})
