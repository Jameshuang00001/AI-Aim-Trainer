"""Phase 2 tests use simulated telemetry and MOCK posting only."""
import copy
import json
import math
from pathlib import Path
import tempfile
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from .controlled_assist import (ControlledLoop, ControlledBackend, ControlledAssistController,
    Limits, MotionBudget, load_calibration, plan_step)
from .test_camera_calibration import state, advance
from .camera_calibration import PLAN, measurement, calibration_report


def calibration():
    return {'gains': (.05, .05), 'fingerprint': (2., 60., 1.5), 'digest': 'test',
            'target': {'resolved_owner_pid': 9900}, 'path': 'mock.report.json'}


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.held = self.focused = True
        self.emergency = False
        self.posts = []
        self.events = []
        self.s = state()
        self.s['time_scale'] = 1.
        self.default_boxes = None
        self.response = (2, 0)
        self.deferred = []
        self.backend = SimpleNamespace(pid=9900, trusted=lambda: True,
            held=lambda: self.held, emergency=lambda: self.emergency, focused=lambda: self.focused,
            validate_destination=lambda: {}, snapshot=lambda: {
                'foreground_pid': 9900 if self.focused else 99, 'accessibility_trusted': True},
            post=self.post)
        self.log = SimpleNamespace(write=lambda r: self.events.append(copy.deepcopy(r)))

    def post(self, method):
        self.assertEqual(method, 'pid')
        self.posts.append(self.loop.core.delta)
        if self.response is not None:
            self.deferred.append(self.loop.core.delta if self.response == 'requested' else self.response)
        return {'input_events_posted': True, 'post_call_returned': True}

    def create(self, dry_run=True):
        self.loop = ControlledLoop(self.backend, self.log, calibration(), None,
                                    dry_run=dry_run, clock=lambda: self.now, wall_clock=lambda: self.now)

    def tick(self, t, boxes=None, changes=None, detection=True, stale=False):
        self.now = t
        if self.deferred:
            for delta in self.deferred: self.s = advance(self.s, delta, realtime=t)
            self.deferred.clear()
        else: self.s = advance(self.s)
        self.s['held'] = self.held
        self.s['sent_at_utc'] = datetime.fromtimestamp(t, timezone.utc).isoformat()
        if changes: self.s.update(changes)
        # This target moves a few pixels after each mocked correction, retaining identity.
        if boxes is None:
            x = 540-len(self.posts)
            boxes = self.default_boxes or [[x, 290, x+20, 310]]
        frame = (900, 600, boxes, [.9]*len(boxes), t) if detection else None
        normal = {**self.s, 'mouse_frame_version': 0, 'mouse_frames': []}
        self.loop.update(normal, t-.3 if stale else t, self.s, t-.3 if stale else t, frame)

    def until(self, condition, duration=12.):
        for i in range(1, int(duration/.05)+1):
            self.tick(round(i*.05, 5))
            if condition(): return
        self.fail('Simulated condition not reached: '+self.loop.reason)

    def test_dry_run_default_produces_three_proposals_and_never_posts(self):
        self.create()
        self.until(lambda: self.loop.done)
        self.assertTrue(self.loop.dry_passed)
        self.assertEqual(self.loop.proposals, 3)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.loop.actual, (0, 0))

    def test_live_requires_feedback_and_new_capture_and_stops_after_burst(self):
        self.create(False)
        self.until(lambda: self.loop.done)
        self.assertGreater(len(self.posts), 0)
        self.assertLessEqual(len(self.posts), 5)
        observed = [e for e in self.events if e['event'] == 'observed_camera_response']
        self.assertTrue(observed)
        self.assertTrue(all(e['controlled_trial_passed'] for e in observed))
        self.assertTrue(any(e['event'] == 'post_correction_detection' for e in self.events))
        self.assertIn(self.loop.reason, ('five_correction_burst_limit', 'ten_second_hold_limit'))
        self.assertTrue(all(delta == (2, 0) for delta in self.posts))

    def test_rmb_release_cancels_pending_without_further_events(self):
        self.create(False); self.until(lambda: len(self.posts) == 1)
        self.held = False
        self.tick(self.now+.05)
        count = len(self.posts)
        self.assertIsNone(self.loop.core.pending)
        for _ in range(15): self.tick(self.now+.05)
        self.assertEqual(len(self.posts), count)

    def test_each_axis_and_sign_is_verified_by_camera_feedback(self):
        for box, expected in (([540, 290, 560, 310], (2, 0)), ([340, 290, 360, 310], (-2, 0)),
                              ([440, 390, 460, 410], (0, 2)), ([440, 190, 460, 210], (0, -2))):
            self.setUp(); self.create(False)
            self.default_boxes = [box]; self.response = 'requested'
            self.until(lambda: any(e['event'] == 'observed_camera_response' for e in self.events))
            self.assertEqual(self.posts, [expected])
            self.assertTrue(next(e for e in self.events if e['event'] == 'observed_camera_response')['controlled_trial_passed'])

    def test_target_loss_or_ambiguity_stops_latched(self):
        for boxes in ([], [[538, 290, 558, 310], [542, 290, 562, 310]], [[-1, 0, 10, 10]]):
            self.setUp(); self.create(False)
            self.until(lambda: self.loop.selected is not None)
            self.tick(self.now+.05, boxes)
            self.assertTrue(self.loop.done)
            self.assertEqual(self.loop.reason, 'target_lost_or_ambiguous')

    def test_focus_loss_pause_menus_cursor_and_stale_telemetry_stop(self):
        for flag in ('focus', 'paused', 'settings_open', 'summary_open', 'cursor_locked', 'stale', 'time_scale'):
            self.setUp(); self.create(False)
            self.until(lambda: self.loop.ever_ready)
            count = len(self.posts)
            if flag == 'focus': self.focused = False
            changes = {flag: flag != 'cursor_locked'} if flag not in ('focus', 'stale') else None
            if flag == 'time_scale': changes = {'time_scale': 0.}
            self.tick(self.now+.05, changes=changes, stale=flag == 'stale')
            self.assertTrue(self.loop.done, flag)
            self.assertEqual(len(self.posts), count)

    def test_emergency_immediate_and_target_detection_staleness(self):
        self.create(False); self.emergency = True; self.tick(.05)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.loop.reason, 'emergency_F8_or_ESC')
        self.setUp(); self.create(False); self.until(lambda: self.loop.selected is not None)
        for _ in range(9): self.tick(self.now+.05, detection=False)
        self.assertTrue(self.loop.done)
        self.assertEqual(self.loop.reason, 'stale_detection')

    def test_fresh_arrival_does_not_hide_queued_old_unity_observation(self):
        self.create(False); self.until(lambda: self.loop.ever_ready)
        old = datetime.fromtimestamp(self.now-1., timezone.utc).isoformat()
        count = len(self.posts)
        self.tick(self.now+.05, changes={'sent_at_utc': old})
        self.assertTrue(self.loop.done)
        self.assertIn('source_timestamp_stale', self.loop.reason)
        self.assertEqual(len(self.posts), count)

    def test_no_response_wrong_axis_gain_or_two_frames_cannot_trigger_followup(self):
        for response in (None, (2, 2), (4, 0), 'two_frames'):
            self.setUp(); self.create(False)
            self.response = response if response != 'two_frames' else None
            self.until(lambda: len(self.posts) == 1)
            if response == 'two_frames': self.deferred = [(2, 0), (2, 0)]
            for _ in range(30): self.tick(self.now+.05)
            self.assertTrue(self.loop.done, response)
            self.assertEqual(len(self.posts), 1)
            self.assertFalse(self.loop.dry_passed)

    def test_inside_deadzone_never_moves_and_resize_fails_closed(self):
        self.create(False)
        for i in range(1, 35): self.tick(i*.05, boxes=[[440, 290, 460, 310]])
        self.assertEqual(self.posts, [])
        self.assertEqual(self.loop.reason, 'inside_deadzone')
        self.now += .05
        self.loop.update(self.s, self.now, self.s, self.now, (901, 600, [], [], self.now))
        self.assertTrue(self.loop.done)
        self.assertEqual(self.loop.reason, 'capture_dimensions_changed')


class CalculationTests(unittest.TestCase):
    def test_projection_signs_deadzone_bounds_and_bad_aspect(self):
        for x, y in ((100, 0), (-100, 0), (0, 100), (0, -100), (100, 90)):
            step = plan_step(x, y, 900, 600, 60, 1.5, (.05, .05), Limits())
            self.assertEqual(math.hypot(*step), 2)
            self.assertGreaterEqual(step[0]*x, 0); self.assertGreaterEqual(step[1]*y, 0)
        self.assertEqual(plan_step(4, 0, 900, 600, 60, 1.5, (.05, .05), Limits()), (0, 0))
        with self.assertRaises(ValueError): plan_step(100, 0, 900, 650, 60, 1.5, (.05, .05), Limits())
        with self.assertRaises(ValueError): Limits(counts_per_second=9)

    def test_acceleration_and_rolling_speed_budget(self):
        budget = MotionBudget(Limits())
        events = []
        for i in range(200):
            t = i*.01
            previous = budget.speed
            if budget.ready(t): budget.consume(t); events.append(t)
            self.assertLessEqual(budget.speed-previous, .16000001)
            self.assertLessEqual(sum(2 for when in events if 0 <= t-when < 1), 8)
        self.assertTrue(events)
        self.assertGreater(events[0], .4)

    def test_successful_recorded_calibration_replays_without_live_game(self):
        directory = Path.home()/'Library/Logs/AI-Aim-Trainer/camera_calibration'
        if not directory.exists(): self.skipTest('Local recorded calibration unavailable')
        c = load_calibration(directory)
        self.assertAlmostEqual(c['gains'][0], .05, places=4)
        self.assertAlmostEqual(c['gains'][1], .05, places=4)

    def test_missing_or_unreliable_calibration_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError): load_calibration(directory)
            (Path(directory)/'bad.report.json').write_text('{"reliable":true}')
            with self.assertRaises(RuntimeError): load_calibration(directory)


class NativeGuardTests(unittest.TestCase):
    def test_default_off_live_needs_confirmation_and_dry_run_proof(self):
        c = ControlledAssistController()
        self.assertEqual(c.snapshot()[0], 'OFF')
        self.assertFalse(c.confirm_live())
        self.assertFalse(c.start(123, dry_run=False))
        c.dry_proof = {'key': ('test',), 'capture_size': (900, 600)}
        self.assertTrue(c.confirm_live())
        c.stop()
        self.assertFalse(c.live_authorized)
        self.assertFalse(c.live_run)

    def test_native_guard_never_dispatches_without_live_and_physical_rmb(self):
        b = object.__new__(ControlledBackend)
        b.controller = SimpleNamespace(post_lock=threading.RLock(), stop_event=threading.Event(),
            dry_run=True, live_run=False, loop=SimpleNamespace(dry_run=True, gates=lambda now: []))
        b.held = lambda: True
        b.emergency = lambda: False
        with patch('coach_app.camera_calibration.CalibrationBackend.post') as post:
            with self.assertRaises(RuntimeError): b.post('pid')
            post.assert_not_called()
            b.controller.dry_run = b.controller.loop.dry_run = False
            b.controller.live_run = True
            b.held = lambda: False
            with self.assertRaises(RuntimeError): b.post('pid')
            with self.assertRaises(RuntimeError): b.before_dispatch()
            post.assert_not_called()
            b.held = lambda: True
            b.post('pid')
            post.assert_called_once_with('pid')
