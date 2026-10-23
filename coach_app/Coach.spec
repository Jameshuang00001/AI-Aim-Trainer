from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root / 'coach_app/packaging_entry.py')], pathex=[str(root)], binaries=[], datas=[], hiddenimports=['keyring.backends.macOS'], excludes=['torch','torchvision','ultralytics','Quartz'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Coach', console=False)
coll = COLLECT(exe, a.binaries, a.datas, name='Coach')
app = BUNDLE(coll, name='Coach.app', bundle_identifier='com.ai-aim-trainer.coach')
