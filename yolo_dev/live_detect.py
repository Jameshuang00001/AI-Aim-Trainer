"""Visual-only Unity head detection. Never controls mouse or shooting."""

import argparse
from collections import deque
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

if __package__:
    from . import capture_unity as capture
else:
    import capture_unity as capture

from coach_app.runtime_paths import MODEL_RELATIVE, resource_root, resolve_model, resolve_editor_crop

try:
    DEFAULT_MODEL = resolve_model()
except FileNotFoundError:
    # Importing helpers remains possible; launch preflight reports every missing path.
    DEFAULT_MODEL = resource_root() / MODEL_RELATIVE


def capture_config(window, explicit=None):
    """Only Editor windows need saved content bounds; games use captured pixels."""
    return resolve_editor_crop(explicit) if window['app'] == 'Unity' else None


def region_for_window(window, width, height, config=None):
    if window['app'] != 'Unity':
        return capture.validate_region((0, 0, width, height), width, height)
    if config is None:
        raise capture.CaptureError('Unity Editor requires an Editor crop; no config path was provided.')
    try:
        return capture.load_game_crop(config, window, width, height)
    except (capture.CaptureError, OSError, ValueError) as error:
        raise capture.CaptureError(f'Unity Editor crop {config}: {error}') from error


def nearest_head(boxes, width, height):
    """Return index, aim point, dx/dy in original crop pixels (right/down positive)."""
    if not boxes:
        return None
    points = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    index = min(range(len(points)), key=lambda i: math.hypot(
        points[i][0] - width / 2, points[i][1] - height / 2))
    x, y = points[index]
    return index, (x, y), (x - width / 2, y - height / 2)


def publish(messages, item):
    # Only the freshest frame matters; never build a backlog of stale detections.
    try:
        messages.get_nowait()
    except queue.Empty:
        pass
    messages.put_nowait(item)


def worker(args, window, messages, stop):
    model_lock = None
    try:
        import fcntl
        cache = capture.CACHE_ROOT
        cache.mkdir(parents=True, exist_ok=True)
        model_lock = (cache / "live-detector.lock").open("a")
        try:
            fcntl.flock(model_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A live detection worker is already running. Stop its preview/assist first.")
        os.environ.setdefault("YOLO_CONFIG_DIR", str(cache / "ultralytics"))
        os.environ.setdefault("MPLCONFIGDIR", str(cache / "matplotlib"))
        import torch
        from ultralytics import YOLO
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS is unavailable. Run with the project's Apple Silicon .venv Python.")
        model = YOLO(str(resolve_model(args.model)))
        if model.names.get(0) != "xbot_head":
            raise RuntimeError(f"Expected class 0 = xbot_head; model classes: {model.names}")
        capture_times, inference_times = deque(maxlen=30), deque(maxlen=30)
        dimensions = None
        last_error = None
        while not stop.is_set():
            started = time.perf_counter()
            try:
                current = next((w for w in capture.unity_windows(args.unity_app_name)
                                if w["id"] == window["id"] and w["pid"] == window["pid"]), None)
                if current is None:
                    raise capture.CaptureError("Unity window unavailable; restore the selected window or quit and reselect its ID.")
                frame = capture.capture_window(current)
            except (capture.CaptureError, subprocess.TimeoutExpired) as exc:
                message = str(exc)
                if message != last_error:
                    print(f"Capture temporarily unavailable: {message}", flush=True)
                last_error = message
                publish(messages, ("status", f"Capture unavailable; retrying. Q quits.\n{message}"))
                stop.wait(0.3)
                continue
            last_error = None
            capture_times.append(time.perf_counter() - started)
            h, w = frame.shape[:2]
            # Revalidate configuration against actual captured pixels, not logical screen coordinates.
            x, y, cw, ch = region_for_window(current, w, h, args.config)
            # Controlled assistance may use an explicitly verified content crop;
            # ordinary detection/preview keeps its existing full-window behavior.
            assist_crop = getattr(args, 'assist_crop', None)
            if assist_crop is not None:
                import hashlib
                if hashlib.sha256(assist_crop.read_bytes()).hexdigest() != args.assist_crop_digest:
                    raise capture.CaptureError('Assist crop changed; stop and repeat dry run.')
                x, y, cw, ch = capture.load_game_crop(assist_crop, current, w, h)
            frame = frame[y:y+ch, x:x+cw].copy()
            if dimensions != (cw, ch):
                dimensions = (cw, ch)
                print(f"Final capture dimensions: {cw} x {ch}; ROI: {(x, y, cw, ch)}", flush=True)
            inference_start = time.perf_counter()
            result = model.predict(frame, device="mps", imgsz=args.imgsz,
                                   conf=args.conf, classes=[0], verbose=False, save=False)[0]
            # CPU conversion waits for MPS, so timing includes completed GPU work.
            boxes = result.boxes.xyxy.cpu().tolist()
            scores = result.boxes.conf.cpu().tolist()
            inference_times.append(time.perf_counter() - inference_start)
            latency = (time.perf_counter() - started) * 1000
            publish(messages, ("frame", (frame, boxes, scores,
                len(capture_times) / sum(capture_times),
                len(inference_times) / sum(inference_times), latency, started)))
    except Exception as exc:
        print(f"Detection error: {type(exc).__name__}: {exc}", flush=True)
        publish(messages, ("error", f"{type(exc).__name__}: {exc}"))
    finally:
        if model_lock is not None:
            model_lock.close()


def draw_frame(payload):
    import cv2
    frame, boxes, scores, capture_fps, inference_fps, latency = payload[:6]
    h, w = frame.shape[:2]
    selected = nearest_head(boxes, w, h)
    for i, (box, score) in enumerate(zip(boxes, scores)):
        left, top, right, bottom = map(round, box)
        color = (0, 220, 255) if selected and selected[0] == i else (70, 220, 70)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.circle(frame, (round((left+right)/2), round((top+bottom)/2)), 3, color, -1)
        cv2.putText(frame, f"head {score:.2f}", (left, max(18, top-6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    center = (w//2, h//2)
    cv2.drawMarker(frame, center, (255, 255, 255), cv2.MARKER_CROSS, 14, 1)
    offset = "No head detected"
    if selected:
        _, point, (dx, dy) = selected
        cv2.line(frame, center, tuple(map(round, point)), (0, 220, 255), 1)
        offset = f"Nearest head dx={dx:+.1f} dy={dy:+.1f} px"
    for i, text in enumerate((f"Capture {capture_fps:.1f} FPS | Inference {inference_fps:.1f} FPS",
                              f"Latency {latency:.1f} ms | {offset}", "VISUAL ONLY | Q to quit")):
        cv2.putText(frame, text, (12, 28+i*26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(frame, text, (12, 28+i*26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", type=int)
    parser.add_argument("--unity-app-name")
    parser.add_argument("--model", type=Path, help="Optional explicit weights path; packaged Coach defaults to its bundled model")
    parser.add_argument("--config", type=Path, help="Unity Editor crop only; standalone games use a full-window ROI")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.imgsz <= 0 or not 0 < args.conf <= 1:
        parser.error("--imgsz must be positive and --conf must be in (0, 1]")
    try:
        args.model = resolve_model(args.model)
        capture.check_permission()
        windows = capture.unity_windows(args.unity_app_name)
        choices = [w for w in windows if args.window_id is None or w["id"] == args.window_id]
        if len(choices) != 1:
            parser.error(f"Select one Unity --window-id from: {windows}")
        args.config = capture_config(choices[0], args.config)
        print(f'Model: {args.model}; capture: {args.config or "standalone full-window (no crop file)"}')
    except (capture.CaptureError, FileNotFoundError) as exc:
        parser.error(str(exc))
    import cv2
    import numpy as np
    title = "XBot head detection - visual only (Q to quit)"
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title, 1100, 650)
    messages, stop = queue.Queue(maxsize=1), threading.Event()
    thread = threading.Thread(target=worker, args=(args, choices[0], messages, stop), daemon=True)
    thread.start()
    status = "Loading local YOLO model on MPS..."
    error = False
    try:
        while True:
            try:
                kind, payload = messages.get_nowait()
                if kind == "frame":
                    cv2.imshow(title, draw_frame(payload))
                    status = None
                else:
                    status = payload
                    error = kind == "error"
            except queue.Empty:
                pass
            if status:
                canvas = np.zeros((650, 1100, 3), dtype=np.uint8)
                import textwrap
                for i, line in enumerate(textwrap.wrap(status, 105) + ["Q to quit"]):
                    cv2.putText(canvas, line, (20, 40+i*28), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (220, 220, 220), 1)
                cv2.imshow(title, canvas)
            if cv2.waitKey(20) & 0xFF in (ord("q"), ord("Q")):
                break
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        cv2.destroyAllWindows()
        thread.join(timeout=16)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
