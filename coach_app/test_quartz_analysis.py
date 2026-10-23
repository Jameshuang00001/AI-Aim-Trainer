import json
from pathlib import Path
import tempfile
import unittest
from coach_app.analyze_quartz_trials import analyze


class QuartzAnalysisTests(unittest.TestCase):
    def report(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows))
            return analyze([path])

    def test_old_success_without_trace_is_not_independent_proof_or_latency(self):
        report=self.report([
            {'event':'posted','test_id':'old','method':'pid','timestamp':'2026-10-22T00:00:00+00:00'},
            {'event':'result','test_id':'old','method':'pid','timestamp':'2026-10-22T00:00:00.4+00:00',
             'unity_received_mouse_x':.05,'unity_received_mouse_y':-.05,'camera_yaw_change':.1,
             'camera_pitch_change':.1,'unity_nonzero_mouse_frames':1,'success':True}])
        self.assertEqual(report['independently_verified_methods'],[])
        self.assertIsNone(report['trials'][0]['arrival_latency_bracket_ms'])
        self.assertEqual(report['trials'][0]['assessment_delay_ms'],400)
        self.assertEqual(report['methods']['pid']['trials_with_phase_trace'],0)

    def test_trace_arrival_bracket_does_not_enable_head_lock(self):
        report=self.report([
            {'event':'posted','test_id':'new','method':'hid','timestamp':'2026-10-22T00:00:00+00:00',
             'post_start_monotonic':10.,'post_end_monotonic':10.,'baseline_receive_monotonic':9.99,
             'baseline_state':{'frame':10,'axis_nonzero_frames':0}},
            {'event':'sample','test_id':'new','method':'hid','receive_monotonic':10.02,
             'state':{'frame':12,'axis_nonzero_frames':1}},
            {'event':'result','test_id':'new','method':'hid','timestamp':'2026-10-22T00:00:00.8+00:00',
             'unity_received_mouse_x':.05,'unity_received_mouse_y':-.05,'camera_yaw_change':.1,
             'camera_pitch_change':.1,'unity_nonzero_mouse_frames':1,'success':True,'controlled_trial_passed':True}])
        bracket=report['trials'][0]['arrival_latency_bracket_ms']
        self.assertAlmostEqual(bracket[0],-10)
        self.assertAlmostEqual(bracket[1],20)
        self.assertFalse(report['head_lock_enabled'])
        self.assertEqual(report['independently_verified_methods'],[])
