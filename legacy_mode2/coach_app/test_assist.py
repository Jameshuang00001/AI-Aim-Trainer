"""Synthetic safety tests: never capture pixels or post real input."""

import json
import math
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coach_app.aimbot import AssistController, HeadTracker, bounded_step
from coach_app.telemetry import CorrectionLog


class SelectionTests(unittest.TestCase):
    def test_nearest_confident_head_and_stability(self):
        tracker = HeadTracker()
        boxes = [[390, 290, 410, 310], [410, 290, 430, 310], [10, 10, 30, 30]]
        self.assertIsNone(tracker.update(boxes, [.49, .8, .9], 800, 600, 0))
        result = tracker.update(boxes, [.49, .8, .9], 800, 600, .1)
        self.assertEqual(result[0], boxes[1])

    def test_identity_retained_and_loss_resets(self):
        tracker = HeadTracker()
        box = [[200, 200, 220, 220]]
        tracker.update(box, [.9], 800, 600, 0)
        first = tracker.update(box, [.9], 800, 600, .1)
        second = tracker.update([[205, 200, 225, 220]], [.9], 800, 600, .2)
        self.assertEqual(first[2], second[2])
        self.assertIsNone(tracker.update([], [], 800, 600, .3))
        self.assertIsNone(tracker.update(box, [.9], 800, 600, .4))
        self.assertNotEqual(first[2], tracker.update(box, [.9], 800, 600, .5)[2])

    def test_teleport_and_ambiguous_heads_disengage(self):
        for boxes in ([[500, 200, 520, 220]], [[198, 200, 218, 220], [202, 200, 222, 220]]):
            tracker = HeadTracker()
            tracker.update([[200, 200, 220, 220]], [.9], 800, 600, 0)
            self.assertIsNone(tracker.update(boxes, [.9]*len(boxes), 800, 600, .1))

    def test_invalid_boxes_and_nan_rejected(self):
        tracker = HeadTracker()
        for box in ([0, 0, 0, 2], [-1, 0, 2, 2], [0, 0, float('nan'), 2], [0, 0, 900, 20]):
            self.assertIsNone(tracker.update([box], [.9], 800, 600, 0))

    def test_step_bounded_and_no_overshoot_command(self):
        self.assertEqual(bounded_step(3, 2, (2, 2)), (0, 0))
        for dx in range(-200, 201, 10):
            for dy in range(-200, 201, 10):
                x, y = bounded_step(dx, dy, (2, 2))
                self.assertLessEqual(math.hypot(x, y), 4)
                self.assertGreaterEqual(x*dx, 0)
                self.assertGreaterEqual(y*dy, 0)
                self.assertLessEqual(abs(x)*2, abs(dx))
                self.assertLessEqual(abs(y)*2, abs(dy))


class ControlTests(unittest.TestCase):
    def test_calibration_correction_acquisition_and_release_pipeline(self):
        controller = AssistController()
        controller.verify()
        state = dict(pid=123, gameplay=True, held=True, emergency=False, yaw=0., pitch=0.,
                     fov=60., aspect=4/3, sensitivity=2.)
        posts, events, failures = [], [], []
        held = [True]

        def move(dx, dy):
            posts.append((dx, dy))
            state['yaw'] += dx*.2
            state['pitch'] += dy*.2
            return True

        backend = SimpleNamespace(emergency=lambda: False, focused=lambda: True,
                                  held=lambda: held[0], move=move)
        receiver = SimpleNamespace(recvfrom=lambda n: (json.dumps(state).encode(), ('127.0.0.1', 9999)))
        messages = queue.Queue(maxsize=1)
        log = SimpleNamespace(write=lambda event: events.append(event))

        def run():
            try:
                # Hypothetical verified backend only; no real native input in tests.
                with patch('coach_app.aimbot.HEAD_LOCK_INPUT_PATH_VERIFIED', True):
                    controller.control_loop(receiver, backend, messages, log, 123)
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.perf_counter()+2
        try:
            while time.perf_counter() < deadline and not any(e.get('successfully_acquired') for e in events):
                box = [390, 290, 410, 310] if len(posts) >= 2 else [405, 305, 425, 325]
                frame = ('frame', (SimpleNamespace(shape=(600,800,3)), [box], [.9],
                                   10, 10, 10, time.perf_counter()))
                try:
                    messages.put_nowait(frame)
                except queue.Full:
                    pass
                time.sleep(.025)
            self.assertFalse(failures)
            self.assertTrue(any(e.get('event') == 'camera_verified' for e in events))
            self.assertTrue(any(e.get('event') == 'correction' for e in events))
            self.assertTrue(any(e.get('successfully_acquired') for e in events))
            held[0] = False
            count = len(posts)
            messages.put_nowait(('frame', (SimpleNamespace(shape=(600,800,3)),
                                           [[405,305,425,325]], [.9], 10, 10, 10, time.perf_counter())))
            time.sleep(.06)
            self.assertEqual(len(posts), count)
            self.assertEqual(controller.snapshot()[0], 'READY')
        finally:
            controller.stop()
            thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_default_off_and_emergency_latches(self):
        controller = AssistController()
        self.assertEqual(controller.snapshot()[0], 'OFF')
        backend = SimpleNamespace(emergency=lambda: True)
        receiver = SimpleNamespace(recvfrom=lambda n: (_ for _ in ()).throw(BlockingIOError()))
        controller.control_loop(receiver, backend, queue.Queue(), None, 123)
        self.assertTrue(controller.stop_event.is_set())

    def test_no_motion_without_verified_camera_even_when_held(self):
        controller = AssistController()
        posted = []
        backend = SimpleNamespace(emergency=lambda: False, focused=lambda: True, held=lambda: True,
                                  move=lambda *delta: posted.append(delta))
        state = dict(pid=123, gameplay=True, held=True, emergency=False, yaw=0, pitch=0,
                     fov=60, aspect=4/3, sensitivity=2)
        receiver = SimpleNamespace(recvfrom=lambda n: (json.dumps(state).encode(), ('127.0.0.1', 9999)))
        messages = queue.Queue()
        for _ in range(3):
            messages.put(('frame', (SimpleNamespace(shape=(600,800,3)), [[500,300,520,320]], [.9],
                                    10, 10, 10, time.perf_counter())))
        thread = threading.Thread(target=controller.control_loop, args=(receiver, backend, messages, None, 123))
        thread.start()
        time.sleep(.1)
        controller.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(posted, [])

    def test_no_duplicate_start_while_detector_stopping(self):
        controller = AssistController()
        controller.detector = SimpleNamespace(is_alive=lambda: True)
        self.assertFalse(controller.start())

    def test_local_telemetry_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            log = CorrectionLog(directory)
            log.write(dict(target_bbox=[1,2,3,4], target_confidence=.9, dx=10, dy=-5,
                           correction_magnitude=2, acquisition_time_ms=100,
                           successfully_acquired=False))
            log.close()
            row = json.loads(log.path.read_text())
            self.assertIn('timestamp', row)
            self.assertEqual(row['correction_magnitude'], 2)
            self.assertFalse(row['successfully_acquired'])

    def test_backend_posts_only_relative_motion_and_rechecks_release(self):
        from coach_app.macos_input import MacMouseBackend
        from unittest.mock import MagicMock
        backend = MacMouseBackend.__new__(MacMouseBackend)
        backend.pid = 123
        backend.q = MagicMock()
        backend.focused = lambda: True
        backend.emergency = lambda: False
        backend.held = lambda: False
        self.assertFalse(backend.move(2, 2))
        backend.q.CGEventPostToPid.assert_not_called()
        backend.held = lambda: True
        self.assertTrue(backend.move(2, 2))
        backend.q.CGEventPostToPid.assert_called_once()
        self.assertEqual(backend.q.CGEventCreateMouseEvent.call_args.args[1], backend.q.kCGEventMouseMoved)
        with self.assertRaises(ValueError):
            backend.move(20, 20)

    def test_detector_lock_rejects_another_worker_before_loading_model(self):
        import fcntl
        from yolo_dev import live_detect as live
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'yolo_dev/.cache'
            cache.mkdir(parents=True)
            with (cache/'live-detector.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                messages = queue.Queue(maxsize=1)
                with patch.object(live.capture, 'CACHE_ROOT', cache):
                    live.worker(SimpleNamespace(), {}, messages, threading.Event())
                kind, message = messages.get_nowait()
                self.assertEqual(kind, 'error')
                self.assertIn('already running', message)


if __name__ == '__main__':
    unittest.main()
