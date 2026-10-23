import json
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from coach_app.aimbot import AssistController, HEAD_LOCK_INPUT_PATH_VERIFIED
from coach_app.compare_mouse_input import compare


class DiagnosticTests(unittest.TestCase):
    def test_comparison_gates_and_does_not_claim_provenance(self):
        base = dict(focused=True, gameplay=True, session_active=True, paused=False,
                    cursor='Locked', look_processed=True, axis_x=0, axis_y=0,
                    raw_axis_x=0, raw_axis_y=0, yaw_delta=0, pitch_delta=0)
        rows = [{**base, 'phase':'physical_baseline', 'axis_x':1, 'raw_axis_x':1, 'yaw_delta':2},
                {**base, 'phase':'synthetic_attempt'},
                {**base, 'phase':'synthetic_attempt', 'focused':False, 'axis_x':5}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows))
            report = compare([path])
        self.assertEqual(report['phases']['synthetic_attempt']['eligible_frames'], 1)
        self.assertIn('upstream', report['finding'])
        self.assertFalse(report['head_lock_enabled'])

    def test_manual_camera_motion_never_unlocks_head_lock(self):
        self.assertFalse(HEAD_LOCK_INPUT_PATH_VERIFIED)
        for yaw_change in (0, .4):
            controller = AssistController()
            controller.verify()
            state = dict(pid=123, gameplay=True, held=True, emergency=False, yaw=0., pitch=0.,
                         fov=60., aspect=4/3, sensitivity=2.)
            posts, events, errors = [], [], []
            def move(*delta):
                posts.append(delta)
                state['yaw'] += yaw_change
                state['pitch'] += yaw_change
                return True
            backend = SimpleNamespace(emergency=lambda:False, focused=lambda:True,
                                      held=lambda:True, move=move)
            receiver = SimpleNamespace(recvfrom=lambda n:(json.dumps(state).encode(),('127.0.0.1',9999)))
            messages = queue.Queue(maxsize=1)
            log = SimpleNamespace(write=lambda event:events.append(event))
            def run():
                try:
                    controller.control_loop(receiver, backend, messages, log, 123)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=run)
            thread.start()
            try:
                deadline = time.perf_counter()+1.2
                while time.perf_counter() < deadline:
                    try:
                        messages.put_nowait(('frame',(SimpleNamespace(shape=(600,800,3)),
                            [[405,305,425,325]],[.9],10,10,10,time.perf_counter())))
                    except queue.Full:
                        pass
                    time.sleep(.025)
                self.assertFalse(errors)
                self.assertEqual(posts, [(2,2)])  # Explicit diagnostic pulse only.
                response = next(e for e in events if e['event']=='diagnostic_camera_response')
                self.assertAlmostEqual(response['yaw_degrees'], yaw_change)
                self.assertFalse(response['synthetic_input_proven'])
                self.assertFalse(any(e['event']=='correction' for e in events))
            finally:
                controller.stop()
                thread.join(1)


if __name__ == '__main__':
    unittest.main()
