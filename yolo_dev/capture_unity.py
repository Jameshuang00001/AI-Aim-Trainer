"""Opt-in window-specific Unity screenshots, not desktop or Coach capture."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coach_app.runtime_paths import project_root, crop_path, cache_root

ROOT = project_root()
CACHE_ROOT = cache_root()
DEFAULT_CONFIG = crop_path()
DEFAULT_OUTPUT = ROOT / "datasets" / "xbot_head" / "raw"
UNITY_APPS = {"Unity", "AI-Aim-Trainer", "AI Aim Trainer"}


class CaptureError(RuntimeError):
    pass


def unity_windows(extra_name=None):
    import Quartz
    allowed = UNITY_APPS | ({extra_name} if extra_name else set())
    rows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    return [dict(id=int(row[Quartz.kCGWindowNumber]), pid=int(row[Quartz.kCGWindowOwnerPID]),
                 app=str(row.get(Quartz.kCGWindowOwnerName, "")),
                 title=str(row.get(Quartz.kCGWindowName, "")),
                 window_size_points=[row.get(Quartz.kCGWindowBounds, {}).get("Width", 0),
                                     row.get(Quartz.kCGWindowBounds, {}).get("Height", 0)])
            for row in rows if row.get(Quartz.kCGWindowOwnerName) in allowed
            and row.get(Quartz.kCGWindowLayer, 0) == 0
            and row.get(Quartz.kCGWindowBounds, {}).get("Width", 0) > 100]


def check_permission(request=False):
    import Quartz
    if Quartz.CGPreflightScreenCaptureAccess():
        return
    if request:
        Quartz.CGRequestScreenCaptureAccess()
    raise CaptureError("Screen Recording permission is missing. In System Settings > Privacy & Security > "
                       "Screen & System Audio Recording (or Screen Recording), allow the Terminal/Python host "
                       "you use for this collector, then restart it. Re-run --request-permission to request access. "
                       "No screenshot was captured.")


def validate_region(region, width, height):
    if not isinstance(region, (list, tuple)) or len(region) != 4 or any(type(v) is not int for v in region):
        raise CaptureError(f"Invalid ROI {region!r}; expected integer (x, y, width, height) "
                           f"within image bounds x=0..{width}, y=0..{height}.")
    x, y, w, h = region
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
        raise CaptureError(f"Invalid ROI (x={x}, y={y}, width={w}, height={h}); "
                           f"right={x+w}, bottom={y+h}; image bounds: "
                           f"width={width}, height={height}, x=0..{width}, y=0..{height}. "
                           "Coordinates must be image-local pixels, not macOS screen coordinates. "
                           "Select the Game region again.")
    return x, y, w, h


def preview_to_image_region(region, preview_width, preview_height, image_width, image_height):
    """Map image-local preview pixels to captured pixels, without a Retina factor."""
    if min(preview_width, preview_height, image_width, image_height) <= 0:
        raise CaptureError("Image and preview dimensions must be positive")
    x, y, w, h = validate_region(region, preview_width, preview_height)
    # Round outward at both edges so small heads are not lost to truncation.
    # Integer arithmetic also avoids floating-point edge errors on odd sizes.
    left = x * image_width // preview_width
    top = y * image_height // preview_height
    right = ((x + w) * image_width + preview_width - 1) // preview_width
    bottom = ((y + h) * image_height + preview_height - 1) // preview_height
    return validate_region((left, top, right-left, bottom-top), image_width, image_height)


def capture_window(window):
    import cv2
    # Native window capture, not -S or -R: other windows (including Coach) are
    # excluded even if they overlap this Unity window. Never grab the desktop.
    with tempfile.TemporaryDirectory(prefix="xbot-unity-") as directory:
        image_path = Path(directory) / "unity.png"
        result = subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-a", "-t", "png",
                                 "-l", str(window["id"]), str(image_path)],
                                capture_output=True, timeout=15, check=False)
        if result.returncode or not image_path.is_file():
            raise CaptureError("macOS could not capture the selected Unity window. Check Screen Recording "
                               "permission, make sure the window is visible/not minimized, and reselect its ID.")
        frame = cv2.imread(str(image_path))
    if frame is None:
        raise CaptureError("The native Unity screenshot could not be decoded")
    return frame


def select_region(frame):
    if __package__:
        from .roi_selector import choose_crop
    else:
        from roi_selector import choose_crop
    region = choose_crop(frame, validate_region, preview_to_image_region)
    if region is None:
        raise CaptureError("Crop selection cancelled. No batch started. Use --crop X Y WIDTH HEIGHT --save-crop to configure without dragging.")
    print(f"Selected image-local ROI: {region}")
    return validate_region(region, frame.shape[1], frame.shape[0])


def save_game_crop(path, window, region, width, height):
    config = dict(app=window["app"], image_size=[width, height], region=list(region),
                  window_size_points=window.get("window_size_points"),
                  coordinate_space="captured_image_pixels", version=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load_game_crop(path, window, width, height):
    if not path.is_file():
        raise CaptureError("No Game View crop is configured yet")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("app") != window["app"]:
        raise CaptureError("Saved Game View crop belongs to a different app or is invalid")
    size = config.get("image_size")
    if size == [width, height]:
        saved_points = config.get("window_size_points")
        if saved_points and window.get("window_size_points") and saved_points != window["window_size_points"]:
            raise CaptureError("Unity logical window size changed; reselect the Game View")
        return validate_region(config.get("region"), width, height)
    # Logical bounds are used only to prove a backing-scale change. Never use
    # their screen origin as image coordinates or assume a Retina multiplier.
    points = window.get("window_size_points")
    if (points and config.get("window_size_points") == points and
            isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size) and
            math.isclose(width / size[0], height / size[1], rel_tol=0.005)):
        region = preview_to_image_region(config.get("region"), size[0], size[1], width, height)
        print(f"Retina backing scale changed: saved image={size}, current={[width, height]}; mapped ROI={region}")
        return region
    raise CaptureError(f"Unity window/image size changed: saved={size}, current={[width, height]}; reselect the Game View")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-windows", action="store_true")
    parser.add_argument("--window-id", type=int)
    parser.add_argument("--unity-app-name", help="Explicit name of a renamed Unity standalone app")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--select-region", action="store_true")
    modes.add_argument("--game-view-only", action="store_true", help="Automatically reuse a Game View crop; configure it once if needed")
    modes.add_argument("--capture-full-window", action="store_true", help="No ROI: save all captured Unity-window pixels")
    modes.add_argument("--region", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"), help="Manual crop in original captured-image pixels; no selector")
    parser.add_argument("--save-crop", action="store_true", help="Save --crop to --config for future --game-view-only runs")
    parser.add_argument("--preview-only", action="store_true", help="Save one test crop and exit without batch capture")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation after saving the test image")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--count", type=int, default=100, help="Finite capture count; Ctrl-C stops early")
    parser.add_argument("--request-permission", action="store_true")
    args = parser.parse_args(argv)
    if args.crop is not None and (args.capture_full_window or args.select_region or args.region is not None):
        parser.error("--crop cannot be combined with --capture-full-window, --select-region or --region")
    if args.save_crop and args.crop is None:
        parser.error("--save-crop requires --crop X Y WIDTH HEIGHT")
    if sys.platform != "darwin":
        parser.error("This collector is for macOS only")
    if not math.isfinite(args.interval) or args.interval < 0.1 or args.count < 1:
        parser.error("Use a finite interval >= 0.1 seconds and count >= 1")
    try:
        windows = unity_windows(args.unity_app_name)
        if args.list_windows:
            for window in windows:
                print(f"{window['id']}  {window['app']}  {window['title']}")
            if not windows:
                print("No visible Unity windows found. Open Unity or the standalone game first.")
            return 0
        if args.window_id is None:
            raise CaptureError("Choose a Unity window ID with --list-windows, then pass --window-id ID")
        window = next((row for row in windows if row["id"] == args.window_id), None)
        if window is None:
            raise CaptureError("That ID is not a visible allowed Unity window. No desktop capture is permitted.")
        check_permission(args.request_permission)
        frame = capture_window(window)
        height, width = frame.shape[:2]
        print(f"Captured image dimensions: width={width}, height={height}")
        if args.crop is not None:
            region = validate_region(args.crop, width, height)
            if args.save_crop:
                save_game_crop(args.config, window, region, width, height)
                print(f"Manual Game View crop saved: {args.config}")
        elif args.capture_full_window:
            region = (0, 0, width, height)
        elif args.select_region or args.region is not None:
            region = select_region(frame) if args.select_region else validate_region(args.region, width, height)
            save_game_crop(args.config, window, region, width, height)
        elif args.game_view_only:
            try:
                region = load_game_crop(args.config, window, width, height)
                print(f"Game View: automatically using saved crop from {args.config}")
            except (CaptureError, ValueError) as error:
                raise CaptureError(f"{error}. Configure once with --select-region (Tk selector with numeric fields), "
                                   "or --crop X Y WIDTH HEIGHT --save-crop (no dragging). "
                                   "To inspect the source image first use --capture-full-window --preview-only. "
                                   f"Captured image bounds: {width}x{height}.") from None
        else:
            region = load_game_crop(args.config, window, width, height)
        output = args.output.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        x, y, w, h = region
        print(f"Final image-local ROI: x={x}, y={y}, width={w}, height={h}")
        test_crop = frame[y:y+h, x:x+w]
        print(f"Final crop dimensions: width={test_crop.shape[1]}, height={test_crop.shape[0]}")
        import cv2
        preview_path = output / f"{run}_preview.png"
        if not cv2.imwrite(str(preview_path), test_crop):
            raise CaptureError(f"Failed to save test screenshot: {preview_path}")
        print(f"Test screenshot saved before batch: {preview_path}", flush=True)
        if args.preview_only:
            return 0
        if sys.stdin.isatty() and not args.yes:
            answer = input("Inspect the test screenshot. Press Enter to start batch, or type q to cancel: ")
            if answer.strip().lower() in ("q", "quit", "n", "no"):
                print("Batch cancelled; test screenshot kept.")
                return 0
        manifest = dict(run_id=run, window=window, image_size=[width, height], region=list(region),
                        interval_seconds=args.interval, preview=preview_path.name, files=[])
        print(f"Capturing only {window['app']} window {window['id']} region {region} -> {output}. Ctrl-C stops.")
        try:
            for index in range(args.count):
                started = time.monotonic()
                live = unity_windows(args.unity_app_name)
                if not any(row["id"] == window["id"] and row["pid"] == window["pid"] for row in live):
                    raise CaptureError("Selected Unity window closed/minimized or changed owner; capture stopped.")
                frame = capture_window(window)
                if frame.shape[:2] != (height, width):
                    raise CaptureError("Unity screenshot dimensions changed. Capture stopped; reselect Game crop.")
                x, y, w, h = region
                filename = f"{run}_{index:05d}_{uuid.uuid4().hex[:8]}.png"
                if not cv2.imwrite(str(output / filename), frame[y:y+h, x:x+w]):
                    raise CaptureError("Failed to save screenshot; check output folder/disk space")
                manifest["files"].append(filename)
                print(f"Saved {filename}", flush=True)
                if index + 1 < args.count:
                    time.sleep(max(0, args.interval - (time.monotonic() - started)))
        finally:
            (output / f"{run}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return 0
    except KeyboardInterrupt:
        print("Capture stopped by user.")
        return 0
    except (CaptureError, OSError, ValueError, subprocess.TimeoutExpired, ImportError) as error:
        print("Capture error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
