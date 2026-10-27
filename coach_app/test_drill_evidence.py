"""Evidence gates and executable exercises, with no live credentials/network."""
import unittest
from coach_app.report_format import drill_options, allowed_drills, measured_report, checked_drill, hit_timing_summary

class DrillEvidenceTests(unittest.TestCase):
    def session(self, assisted=False):
        s = dict(shots=20, hits=19, misses=1, accuracy=95,
                 shots_detail=[dict(hit=True, reaction_ms=x) for x in [500]*10+[1200]*9])
        if assisted:
            s['aim_corrections'] = [dict(initial_error_deg=4, remaining_error_deg=1)]*13
        return s

    def test_manual_and_assisted_have_distinct_choices(self):
        manual, assist = allowed_drills(self.session()), allowed_drills(self.session(True))
        self.assertIn('controlled_pace', manual)
        self.assertIn('steady_acquisition', manual)
        self.assertNotIn('baseline', manual)
        self.assertNotIn('controlled_pace', assist)
        self.assertIn('manual_landing', assist)
        self.assertIn('assist_comparison', assist)

    def test_small_sample_does_not_diagnose_speed(self):
        self.assertEqual(list(allowed_drills({'shots':3,'hits':3})), ['baseline'])
        s=self.session(); s['shots_detail']=s['shots_detail'][:9]
        self.assertNotIn('controlled_pace', allowed_drills(s))
        self.assertNotIn('steady_acquisition', allowed_drills(s))

    def test_invalid_timing_and_misses_not_timed_as_hits(self):
        s={'shots_detail':[dict(hit=True,reaction_ms=x) for x in [None,'bad',float('nan'),float('inf'),-1,0]]+
           [dict(hit=False,reaction_ms=100)]*20}
        self.assertIsNone(hit_timing_summary(s))

    def test_even_sample_median_and_quartiles(self):
        s={'shots_detail':[dict(hit=True,reaction_ms=x) for x in range(100,1200,100)]}
        result=hit_timing_summary(s)
        self.assertEqual(result['median'],600)
        self.assertEqual(result['lower'],350)
        s['shots_detail'].pop()
        self.assertEqual(hit_timing_summary(s)['median'],550)

    def test_every_rendered_choice_includes_local_evidence(self):
        s=self.session(True)
        for key, option in drill_options(s).items():
            report=measured_report(s,key,source='Test online selection')
            self.assertIn(option['evidence'],report)
            self.assertIn('Why this exercise:', report)
            self.assertIn('assistance off', report)
        self.assertIn('Static Targets in Settings',measured_report(s,'manual_landing'))

    def test_unsupported_advice_cannot_enter_report(self):
        with self.assertRaises(ValueError):
            checked_drill('{"drill_id":"controlled_pace"}',self.session(True))
        with self.assertRaises(ValueError):
            checked_drill('{"drill_id":"baseline","reason":"invented"}',{})
