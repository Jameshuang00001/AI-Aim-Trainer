"""Opt-in, fail-closed head assistance exclusively for this Unity aim trainer.

No firing. Requires a read-only Unity heartbeat, foreground matching PID, physical
RMB, stable fresh detections and measured relative camera response. Stop/F8/ESC
latches OFF; only explicit Start can arm again. No Tk calls occur on workers.
"""

import math
import queue
import socket
import json
import threading
import time
from types import SimpleNamespace

# Investigation interlock: camera motion alone may be physical user input.
# No environment setting or UI action can enable correction output during this audit.
HEAD_LOCK_INPUT_PATH_VERIFIED = False

if __package__:
    from .telemetry import CorrectionLog
    from .macos_input import MacMouseBackend
else:
    from telemetry import CorrectionLog
    from macos_input import MacMouseBackend


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def bounded_step(dx, dy, pixels_per_count, gain=0.35, maximum=4):
    """Conservative proportional delta; dead zone avoids rounding oscillations."""
    if math.hypot(dx, dy) <= 8:
        return (0, 0)
    x, y = dx * gain / pixels_per_count[0], dy * gain / pixels_per_count[1]
    length = math.hypot(x, y)
    scale = min(1, maximum / max(length, 1e-9))
    x, y = round(x * scale), round(y * scale)
    # Integer rounding must not violate the radial bound.
    while math.hypot(x, y) > maximum:
        if abs(x) >= abs(y):
            x -= 1 if x > 0 else -1
        else:
            y -= 1 if y > 0 else -1
    return x, y


class HeadTracker:
    def __init__(self):
        self.serial = 0
        self.reset()

    def reset(self):
        self.box = None
        self.stable = 0
        self.started = None

    def update(self, boxes, scores, width, height, now):
        candidates = [(b, s) for b, s in zip(boxes, scores)
                      if s >= 0.5 and len(b) == 4 and all(math.isfinite(v) for v in (*b, s))
                      and 0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height]
        if not candidates:
            self.reset()
            return None
        if self.box is None:
            box, score = min(candidates, key=lambda item: math.dist(center(item[0]), (width/2, height/2)))
            self.serial += 1
            self.started = now
        else:
            old_area = (self.box[2]-self.box[0]) * (self.box[3]-self.box[1])
            gate = max(24, math.sqrt(old_area) * 1.5)
            matches = sorted(candidates, key=lambda item: math.dist(center(item[0]), center(self.box)))
            box, score = matches[0]
            distance = math.dist(center(box), center(self.box))
            ratio = (box[2]-box[0]) * (box[3]-box[1]) / old_area
            if (distance > gate or not 0.5 <= ratio <= 2 or
                    len(matches) > 1 and math.dist(center(matches[1][0]), center(self.box)) - distance < 8):
                self.reset()  # Do not jump straight to a different/ambiguous head.
                return None
        self.box = box
        self.stable += 1
        return (box, score, self.serial) if self.stable >= 2 else None


class AssistController:
    def __init__(self):
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = self.detector = None
        self.status, self.detail = "OFF", "Head Lock disabled during mouse-input investigation; detection and diagnostic Verify remain available."
        self.verify_requested = False

    def snapshot(self):
        with self.lock:
            return self.status, self.detail

    def set_status(self, status, detail):
        with self.lock:
            if not self.stop_event.is_set() or status == "OFF":
                self.status, self.detail = status, detail

    def stop(self):
        # Serialize Stop against posting: no posts after this method returns.
        with self.lock:
            self.stop_event.set()
            self.status, self.detail = "OFF", "Stopped. Press Start to arm again."

    def verify(self):
        with self.lock:
            self.verify_requested = True

    def start(self, window_id=None):
        with self.lock:
            if self.thread and self.thread.is_alive() or self.detector and self.detector.is_alive():
                return False  # A loading/stopping model must finish before another starts.
            self.stop_event = threading.Event()
            self.verify_requested = False
            self.status, self.detail = "READY", "Loading detector; Head Lock disabled during mouse-input investigation."
            self.thread = threading.Thread(target=self.run, args=(window_id,), daemon=True)
            self.thread.start()
            return True

    def run(self, window_id):
        receiver = log = None
        try:
            # Coach can be launched as a script; add only our project directory.
            import sys
            from pathlib import Path
            root = Path(__file__).resolve().parents[1]
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from yolo_dev import live_detect as live
            capture = live.capture
            capture.check_permission()
            windows = [w for w in capture.unity_windows() if window_id is None or w["id"] == window_id]
            if len(windows) != 1:
                raise RuntimeError(f"Enter a Unity window ID; visible choices: {[(w['id'], w['title']) for w in windows]}")
            window = windows[0]
            model_path = live.resolve_model()
            config_path = live.capture_config(window)
            print(f"[assist] YOLO model: {model_path}; window {window['id']} ({window['app']}); "
                  f"capture: {config_path or 'standalone full-window (no crop file required)'}", flush=True)
            backend = MacMouseBackend(window["pid"], window_id=window["id"])
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.bind(("127.0.0.1", 8766))
            receiver.setblocking(False)
            log = CorrectionLog()
            print(f"[assist] Local telemetry: {log.path}", flush=True)
            messages = queue.Queue(maxsize=1)
            args = SimpleNamespace(model=model_path, config=config_path,
                                   imgsz=640, conf=0.5, unity_app_name=None)
            self.detector = threading.Thread(target=live.worker, args=(args, window, messages, self.stop_event), daemon=True)
            self.detector.start()
            self.control_loop(receiver, backend, messages, log, window["pid"])
        except Exception as exc:
            with self.lock:
                self.stop_event.set()
                self.status, self.detail = "OFF", f"{type(exc).__name__}: {exc}"
            print(f"[assist] {self.detail}", flush=True)
        finally:
            self.stop_event.set()
            if receiver:
                receiver.close()
            if log:
                log.close()

    def control_loop(self, receiver, backend, messages, log, pid):
        tracker = HeadTracker()
        state, received = None, 0
        pixels_per_count = calibration = fingerprint = None
        pending = None
        correction_id = 0
        calibrated_at = 0
        last_frame = 0
        frame_size = None
        while not self.stop_event.wait(0.01):
            now = time.perf_counter()
            # Drain bounded batches so malformed traffic cannot starve Stop checks.
            for _ in range(32):
                try:
                    data, address = receiver.recvfrom(4096)
                except BlockingIOError:
                    break
                try:
                    candidate = json.loads(data)
                    if address[0] != "127.0.0.1" or candidate["pid"] != pid:
                        continue
                    if not all(type(candidate[k]) is bool for k in ("gameplay", "held", "emergency")):
                        continue
                    if not all(isinstance(candidate[k], (int, float)) and math.isfinite(candidate[k])
                               for k in ("yaw", "pitch", "fov", "aspect", "sensitivity")):
                        continue
                    if not (1 < candidate["fov"] < 179 and candidate["aspect"] > 0):
                        continue
                    state, received = candidate, now
                except (KeyError, TypeError, ValueError):
                    continue
            if backend.emergency() or state and state["emergency"] and now-received < 0.2:
                self.stop()
                break
            safe = (state is not None and now-received < 0.2 and state["gameplay"] and state["held"]
                    and backend.focused() and backend.held())
            current_fingerprint = ((state["sensitivity"], state["fov"], state["aspect"])
                                   if state else None)
            if fingerprint is not None and fingerprint != current_fingerprint:
                pixels_per_count = calibration = None
                fingerprint = None
            if not safe or now-last_frame > 0.5:
                if pending:
                    log.write({**pending, "event": "acquisition_result", "successfully_acquired": False, "outcome": "disengaged"})
                    pending = None
                tracker.reset()
                calibration = None
                if state is None or now-received >= 0.2:
                    detail = "No fresh Unity state: attach AssistStatePublisher and assign Main Camera (UDP 8766)."
                else:
                    detail = ("Hold RMB in active Unity gameplay." if pixels_per_count else
                              "Hold RMB in active Unity gameplay. Verify camera before assistance.")
                self.set_status("READY", detail)
            if safe and self.verify_requested and frame_size:
                with self.lock:
                    self.verify_requested = False
                    pixels_per_count = None
                    if not self.stop_event.is_set() and backend.move(2, 2):
                        log.write({"event": "verification_pulse_posted", "requested_delta": [2, 2],
                                   "dispatch": "CGEventPostToPid", "delivery_verified": False,
                                   "head_lock_enabled": False})
                        calibration = (dict(state), received, now, frame_size)
                        self.set_status("READY", "Verifying relative camera response; keep mouse still.")
            if calibration and now-calibration[2] >= 0.25 and safe:
                before, sent_state_time, sent, (width, height) = calibration
                if received <= sent_state_time or now-sent > 0.6:
                    raise RuntimeError("Camera verification timed out. No assistance enabled.")
                yaw = (state["yaw"]-before["yaw"]+180) % 360-180
                pitch = (state["pitch"]-before["pitch"]+180) % 360-180
                calibration = None
                response_in_bounds = 0.005 < yaw < 3 and 0.005 < pitch < 3
                log.write({"event": "diagnostic_camera_response", "yaw_degrees": yaw, "pitch_degrees": pitch,
                           "response_in_existing_bounds": response_in_bounds,
                           "synthetic_input_proven": False, "head_lock_enabled": False})
                if not HEAD_LOCK_INPUT_PATH_VERIFIED:
                    pixels_per_count = None
                    self.set_status("READY", f"Diagnostic only: yaw={yaw:.4f}, pitch={pitch:.4f}. Head Lock disabled; compare Unity mouse logs.")
                    continue
                if not response_in_bounds:
                    raise RuntimeError(f"Relative camera verification failed (yaw={yaw:.4f}, pitch={pitch:.4f}). "
                                       "Unity may ignore injected deltas. No cursor warp or fallback used.")
                vertical = math.tan(math.radians(state["fov"] / 2))
                pixels_per_count = (width * math.tan(math.radians(yaw)) / (4*vertical*state["aspect"]),
                                    height * math.tan(math.radians(pitch)) / (4*vertical))
                fingerprint = current_fingerprint
                calibrated_at = now
                log.write({"event": "camera_verified", "yaw_degrees": yaw, "pitch_degrees": pitch,
                           "pixels_per_count": pixels_per_count})
                self.set_status("READY", "Camera verified. Hold RMB; F8/ESC stops.")
                tracker.reset()
            try:
                kind, payload = messages.get_nowait()
            except queue.Empty:
                continue
            if kind == "error":
                raise RuntimeError(payload)
            if kind != "frame":
                tracker.reset()
                self.set_status("READY", str(payload))
                continue
            frame, boxes, scores = payload[:3]
            captured = payload[6]
            h, w = frame.shape[:2]
            if frame_size and frame_size != (w, h):
                pixels_per_count = calibration = None
            frame_size = (w, h)
            last_frame = captured
            if not safe or now-captured > 0.5 or captured <= calibrated_at or not pixels_per_count or calibration:
                tracker.reset()
                continue
            selected = tracker.update(boxes, scores, w, h, now)
            if pending:
                acquired = bool(selected and selected[2] == pending["target_id"] and
                                math.dist(center(selected[0]), (w/2, h/2)) <= 8)
                log.write({**pending, "event": "acquisition_result", "successfully_acquired": acquired,
                           "acquisition_time_ms": round((now-pending["acquisition_started"])*1000, 1)})
                pending = None
            if not selected:
                self.set_status("READY", "Waiting for a stable, confident head detection.")
                continue
            box, confidence, identity = selected
            x, y = center(box)
            dx, dy = x-w/2, y-h/2
            step = bounded_step(dx, dy, pixels_per_count)
            # Recheck all native safety conditions immediately before each event.
            with self.lock:
                if (not HEAD_LOCK_INPUT_PATH_VERIFIED or self.stop_event.is_set()
                        or not backend.held() or not backend.focused() or backend.emergency()):
                    continue
                if step != (0, 0) and backend.move(*step):
                    correction_id += 1
                    pending = {"event": "correction", "correction_id": correction_id,
                               "target_id": identity, "target_bbox": box,
                               "target_confidence": confidence, "dx": dx, "dy": dy,
                               "correction_delta": list(step), "correction_units": "relative_mouse_counts",
                               "correction_magnitude": math.hypot(*step),
                               "acquisition_started": tracker.started,
                               "acquisition_time_ms": round((now-tracker.started)*1000, 1)}
                    log.write({**pending, "successfully_acquired": False, "outcome": "pending_observation"})
                self.set_status("ACTIVE", f"Head {identity} | dx {dx:+.0f}, dy {dy:+.0f} px | F8/ESC stops")
        if pending:
            log.write({**pending, "event": "acquisition_result", "successfully_acquired": False, "outcome": "stopped"})
