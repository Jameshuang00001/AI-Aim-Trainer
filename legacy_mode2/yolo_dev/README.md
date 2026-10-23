# XBot Head Dataset: Phase 1

This phase installs development tools and collects real Unity screenshots only.
It does not load model weights, train, run detection, move the mouse, or shoot.
Coach UI, Keychain credentials, Nebius analysis, and Unity IPC stay separate.

## Environment

Verified setup: Python 3.13.5 arm64, torch 2.14.1, torchvision 0.29.1,
ultralytics 8.4.178, opencv-python 4.14.0.94, mss 10.2.0, Quartz bindings 12.2.2.
MPS available=True and the GPU/CPU tensor comparison passed outside the restricted
execution sandbox (inside it, the Metal device was not visible). pip check passed.
Existing OpenAI 2.54.0, Keyring 25.7.0, and Cocoa bindings 12.2.2 were preserved.
At setup time no visible Unity window was found and Screen Recording preflight
was denied. No real screenshot/overlay-exclusion test has been performed yet;
the collector's native-window command and crop/save behavior passed mocked tests.

From the project root:

```sh
.venv/bin/python -m pip install -r requirements-yolo.txt
.venv/bin/python yolo_dev/check_environment.py
.venv/bin/python -m pip check
```

The requirements pin the versions installed for arm64 Python 3.13. Run with the
existing .venv, not Rosetta/x86 Python. The check imports packages and performs
a tiny MPS tensor calculation plus a torchvision operator check. No training
or weight download occurs. MPS must report available and its calculation must
pass before considering GPU setup verified. Apple documents the backend at
https://developer.apple.com/metal/pytorch/ and PyTorch documents device checks at
https://docs.pytorch.org/docs/stable/notes/mps.html.

## Choose the Unity Window and Game Crop

### Automatic Game View Capture After One-Time Setup

```sh
.venv/bin/python yolo_dev/capture_unity.py --list-windows
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --select-region --preview-only
```

Replace 123 with your Unity window ID. Configure once by selecting **only actual
gameplay content**, excluding the Game tab, playback toolbar, black letterbox bars,
Hierarchy, Inspector, and Console. The crop is saved locally. Future runs reuse it
automatically without selection:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --game-view-only --interval 1 --count 100
```

### No-Dragging Manual Crop

If mouse selection fails, use numeric crop coordinates directly. First save a
full-window preview with `--capture-full-window --preview-only`, inspect its image
dimensions in an image viewer, and identify the Game area's pixel rectangle.
Then use (replace these example values with your actual rectangle):

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --crop 100 200 1200 700 --save-crop --preview-only
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --game-view-only --count 100
```

`--crop X Y WIDTH HEIGHT` always uses original captured-image pixels with origin
at the image's top-left, never macOS desktop coordinates. Without `--save-crop`,
it applies only to that run; with the flag it writes the local `--config` file.
The legacy `--region` option still saves a crop as before. `--game-view-only`
without a valid configuration now prints setup instructions rather than opening
a selector unexpectedly.

This deliberately uses one-time configuration, not unreliable image-color/title
heuristics or Accessibility inspection of Unity panels. It preserves source image
pixels: only the selector preview is resized, never the saved gameplay crop.
The final saved width/height are printed and a test image precedes every batch.

If capture pixel dimensions change while the logical window dimensions remain
identical, the crop is proportionally remapped using the actual image-size ratio.
Other size/app changes require selection again. Same-size Editor layout changes
(moving a panel, changing Game aspect ratio/letterboxing, switching Game to Scene)
cannot be detected reliably: rerun `--select-region` after such changes.
Use separate `--config` files for different Editor layouts or standalone windows.
During a batch, size/owner changes still stop capture instead of saving a bad crop.
`--game-view-only` is exclusive with the other capture-mode flags.

Open Unity Play Mode or your AI-Aim-Trainer standalone. Detaching/maximizing the
Game tab makes a clean viewport easier to select. Do not use Desktop capture.

```sh
.venv/bin/python yolo_dev/capture_unity.py --list-windows
```

Choose the ID for the window containing Game view (not Scene, Inspector, or Hub):

For the simplest diagnostic, save the entire Unity window once without ROI selection:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --capture-full-window --preview-only
```

This creates a uniquely named `*_preview.png` in raw and exits before the batch.
It captures only the selected Unity window, not overlapping Coach pixels or the
desktop. For the Editor, this mode can include Editor UI; use the Game crop below
for clean dataset images. A standalone window is usually simpler for full-window
capture. Omit `--preview-only` to collect a batch.

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --select-region --interval 1 --count 100
```

Replace 123 with the listed ID. In the preview, drag a box around **only the Game
viewport**, excluding Editor tabs/toolbars. Enter confirms; Escape cancels.
Selection uses user input only, never automated mouse control.
On Retina displays the crop uses actual screenshot pixels, not macOS points.
The selector now uses Tkinter and Pillow, not OpenCV's macOS HighGUI callbacks.
An all-zero OpenCV ROI means no rectangle was accepted (missing drag events or
cancellation); scaling an empty rectangle cannot repair that failure. The new
selector has its own Canvas press/drag/release handlers and also provides four
numeric entry fields, so no dragging is required. It resizes a preview image to
fit the display while retaining aspect ratio; the preview window is not resizable.
Canvas events are image-local preview coordinates. Rectangle edges are mapped back
to the original image using the actual image/preview width and height ratios;
no screen origin, Quartz logical bounds, or assumed 2x Retina factor is used.
The collector prints image size, preview size, final image-local ROI,
and final crop dimensions. Invalid ROIs report coordinates and actual bounds.
Empty/invalid numeric selections remain in the selector with a detailed validation
message. Cancel or Escape exits without starting a batch.

Every valid run saves a test crop before batch capture. In an interactive Terminal,
inspect the printed `*_preview.png` path and press Enter to start the batch, or q
to cancel. Use `--preview-only` to stop after the test image, or `--yes` to skip
the confirmation. A noninteractive run saves the preview and proceeds without
prompting. Preview images are not included in the manifest's batch `files` list;
exclude them from labeling to avoid duplicating the first scene composition.

Repeat with the saved crop:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --interval 1.5 --count 200
```

For a known crop, use `--region X Y WIDTH HEIGHT` in original captured-image pixels,
not screen coordinates. `--capture-full-window`, `--select-region`, and `--region`
are mutually exclusive. A renamed Unity build
can be selected explicitly with `--unity-app-name "Your Unity App Name"`.
The window must belong to that named application, never a desktop or Coach ID.
Keep the same Game-tab layout while collecting. Reselect after resizing the
window, changing display/Retina scale, or moving/resizing the Game tab inside
the Editor. Window closure, minimization, owner changes, or size changes stop
collection rather than silently recording a different region. Ctrl-C stops early.

### Capture Privacy and Permissions

The collector calls macOS `screencapture -l <window-id>` in **window-only** mode,
without desktop-compositing flags. Coach and other overlapping windows are not
part of that window's backing pixels. Each full Unity-window frame is temporary;
only the selected Game crop is retained in `datasets/xbot_head/raw/`. No network
upload, audio, or screen recording video is used. `mss` is installed for future
experiments but deliberately not used for a composited desktop crop here.

Screen Recording access is required. If the permission check fails, no screenshot
is taken. Enable the actual host (Terminal/iTerm/your Python runner as listed by
macOS) in System Settings > Privacy & Security > Screen & System Audio Recording
(or Screen Recording), then restart that host. To request the OS prompt explicitly:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id 123 --select-region --request-permission
```

The tool never changes existing Coach permissions, Accessibility settings,
Keychain access, or Unity gameplay. No permission prompt is requested unless you
use the flag. Permission approval itself remains your choice.

## Collection Plan

- Start with several short runs rather than thousands of nearly identical frames.
  A 0.75-2 second interval is a useful starting point. Inspect image quality first.
- Vary close, medium, and far XBots, plus frontal, side, and oblique head views.
  Move/aim manually in your own Unity trainer; do not automate controls.
- Include single bots and multiple bots; label every visible head in each image.
- Vary idle/walking poses, partial occlusion, arena backgrounds, and lighting only
  through normal existing gameplay/settings. Decide whether falling/dead heads
  belong in the target task; apply the same rule to every split.
- Include genuine empty-arena/negative images. Remove blurred, broken, duplicate,
  or ambiguous frames. Do not fabricate positive examples or label body centers.
- Raw filenames have a run ID, sequence number, and random suffix. Each run has a
  JSON manifest recording crop/window metadata and successful filenames. Keep
  these run groups intact when splitting to avoid temporal leakage.

## Labeling

### Built-In Local Annotator

```sh
.venv/bin/python yolo_dev/annotate.py
```

Uses existing Tkinter/Pillow dependencies. No upload, model, training, or Coach
connection is involved. Override the dataset root with `--dataset /path/to/xbot_head`
if necessary. PNG, JPG, and JPEG files under raw are listed in filename order;
metadata JSON, hidden files, and filenames containing preview are skipped.
Duplicate image stems are rejected to prevent different images sharing a label.

- Draw mode: drag a rectangle around each head; multiple heads are supported.
  Boxes use original-image pixels regardless of Retina scaling or window size.
- Select mode: click a box, or select its Head entry in the side list. Delete Box
  removes it. Undo restores the previous box edit; Command-Z/Control-Z also work.
- Every completed box edit, deletion, undo, navigation, and close autosaves.
  Next/Previous (or arrow keys) switch images. History resets on navigation.
- Mark Reviewed when all heads are correct. Reviewed + Next marks and advances.
  A genuine negative image must be explicitly Reviewed with zero boxes. Editing
  boxes clears Reviewed until checked again, preventing accidental incomplete exports.
- Work is stored locally in annotations/<image-stem>.txt as YOLO labels, with
  reviewed state in annotations/progress.json. Reopening resumes saved labels and
  reviewed state. Changed source-image size/mtime invalidates its reviewed status.
  Keep raw images unchanged while annotating. Do not open simultaneous annotators
  on the same dataset; progress is designed for one local editing process.

After reviewing every image, click Export 80/20. At least two images are required.
Images and labels are copied into images/train, images/val, labels/train, labels/val.
The split is deterministic (seed 42), with validation count rounded to the nearest
20% and at least one image per split. Capture runs are kept together when whole
runs match that count; otherwise a warning identifies image-level splitting and
possible near-duplicate leakage. Collect suitably sized independent runs for a
clean held-out set. Review split_manifest.json before any future training.

Export does not change raw images or working annotations. Previous output folders
are backed up under annotation_backups/ before replacement; incomplete publication
rolls back. These files and local annotations are Git-ignored. No training starts.

Tests:

```sh
.venv/bin/python -m unittest yolo_dev.test_annotations -v
YOLO_GUI_TESTS=1 .venv/bin/python -m unittest yolo_dev.test_annotator_ui -v
```

The GUI test opens synthetic images and invokes local callbacks only; it does not
capture screens, move the OS mouse, access Keychain, or call Nebius.

Use a bounding-box annotation tool that exports **YOLO object detection** labels.
No annotation service is installed or uploaded to automatically. Class 0 is
`xbot_head`; there are no other classes in this phase.

Draw a tight axis-aligned rectangle around the visible head (not neck, torso,
weapon, or a head-shaped shadow). Keep the occlusion policy consistent. Review
tiny distant heads carefully; discard uncertain images rather than omit a known
head and accidentally teach it as background. Label all eligible heads.

For each `frame.png`, create `frame.txt` with one line per head:

```text
0 0.500000 0.250000 0.080000 0.120000
```

Format is `class x_center y_center width height`, normalized by the **saved crop's**
width and height (not full screenshot size). Values must be between 0 and 1;
width/height must be positive. True negative images should have empty `.txt` files.
Never add an empty label file to an image that contains an eligible head.

## Train/Validation Split

Reserve about 20% of **entire capture runs** for validation and use the other
80% for training. Use different scene compositions/distances in held-out runs.
Do not randomly distribute adjacent frames or near-duplicates across splits.
Do not augment before splitting. Keep validation fixed for future comparisons.

Copy reviewed image/label pairs into:

```text
datasets/xbot_head/images/train/frame.png
datasets/xbot_head/labels/train/frame.txt
datasets/xbot_head/images/val/other_frame.png
datasets/xbot_head/labels/val/other_frame.txt
```

The `data.yaml` contains the explicit project dataset path and class 0. Update
its path if you move the project. Empty train/val folders are intentional until
labeling is complete. Screenshots, labels, raw manifests, local crop config, and
caches are Git-ignored to avoid accidentally committing captures. Review them
locally; do not commit model artifacts. No training command is run in Phase 1.

## Offline Collector Tests

## Live Head Detection Preview

Run from the project root while Unity gameplay is visible:

```sh
.venv/bin/python yolo_dev/capture_unity.py --list-windows
.venv/bin/python yolo_dev/live_detect.py --window-id YOUR_ID --imgsz 640 --conf 0.25
```

Uses local `baseline_v1/weights/best.pt`, MPS, and the saved Game View crop.
Configure the crop first using `capture_unity.py --select-region --preview-only`
or `--crop X Y WIDTH HEIGHT --save-crop --preview-only`. Reconfigure after moving
Editor panels. No full-desktop capture or mouse/shooting control is performed.

The separate resizable preview shows boxes, confidence, head-center dots, and
the nearest head highlighted yellow. Crosshair means the exact crop center;
dx is positive right, dy positive down, in original crop pixels, independent of
preview resizing or Retina scaling. Include only gameplay content in your crop.
Press Q in the preview or close it to stop. No frames or predictions are saved.

Capture and inference FPS are rolling stage processing rates (not game FPS or
combined preview throughput). Latency measures capture-start through completed
inference, excluding display time. Native window capture uses a subprocess and
PNG decoding, so capture can bottleneck. First inference includes warm-up.
Temporary unavailable-window/capture errors retry without showing stale boxes;
invalid crops/model errors require fixing configuration and restarting. MPS must
be available; there is no silent CPU fallback. Screen Recording permission is
checked without requesting or changing it automatically.

## Offline Tests

```sh
.venv/bin/python -m unittest yolo_dev.test_capture -v
```

These use synthetic in-memory fixtures and mocked native capture only; they do
not take screenshots, grant permissions, move input, or make model/API calls.
