"""After Mode2Build.Build, assemble a self-contained macOS app (no credentials)."""
import argparse
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path, help='New output .app path')
args = parser.parse_args()
destination = args.destination.resolve()
if destination.exists():
    raise SystemExit('Destination exists; choose a new path to preserve the previous release.')
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(root/'build/portable-coach'),
                '--workpath', str(root/'build/portable-coach-work'), str(root/'coach_app/Coach.spec')], cwd=root, check=True)
source = root/'build/Mode2/AI-Aim-Trainer.app'
if not source.is_dir(): raise SystemExit('Build Unity first with Mode2Build.Build')
subprocess.run(['ditto', str(source), str(destination)], check=True)
helper = destination/'Contents/Helpers/Coach.app'
subprocess.run(['ditto', str(root/'build/portable-coach/Coach.app'), str(helper)], check=True)
for path in destination.rglob('coach-root.txt'):
    path.write_text('')
for path in destination.rglob('*'):
    if path.is_symlink() and not path.resolve().is_relative_to(destination):
        raise SystemExit(f'External symlink: {path}')
subprocess.run(['codesign','--force','--deep','--sign','-',str(destination)], check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(destination)], check=True)
print(destination)
