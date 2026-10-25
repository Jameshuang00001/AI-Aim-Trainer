import unittest
from coach_app.report_format import prepare_session
from coach_app.nebius_client import SYSTEM_PROMPT

class AssistAnalysisTests(unittest.TestCase):
    def test_summary_keeps_every_record_and_excludes_unsettled_from_settle_mean(self):
        records = [dict(initial_error_deg=2, remaining_error_deg=.1, path_length_deg=3, duration_ms=600, time_to_settle_ms=200, speed_deg_per_second=30, initial_yaw_error_deg=-2, initial_pitch_error_deg=1),
                   dict(initial_error_deg=4, remaining_error_deg=1, path_length_deg=5, duration_ms=800, time_to_settle_ms=-1, speed_deg_per_second=90, initial_yaw_error_deg=2, initial_pitch_error_deg=-3)]
        prepared=prepare_session(dict(aim_corrections=records))
        self.assertEqual(len(prepared['aim_corrections']),2)
        summary=prepared['aim_correction_summary']
        self.assertEqual(summary['acquisitions'],2)
        self.assertEqual(summary['settled_acquisitions'],1)
        self.assertEqual(summary['mean_time_to_settle_ms'],200)
        self.assertEqual(summary['mean_applied_path_deg'],4)
        self.assertEqual(summary['mean_speed_deg_per_second'],60)
        self.assertEqual(summary['mean_signed_yaw_error_deg'],0)
        self.assertEqual(summary['mean_signed_pitch_error_deg'],-1)
    def test_empty_session_has_no_fabricated_assist_measurements(self):
        summary=prepare_session(dict(aim_corrections=[]))['aim_correction_summary']
        self.assertEqual(summary['acquisitions'],0)
        self.assertIsNone(summary['mean_entry_error_deg'])
    def test_analysis_prompt_requires_assist_measurements_and_skill_distinction(self):
        self.assertIn('allowed_drills',SYSTEM_PROMPT)
        self.assertIn('Do not write statistics',SYSTEM_PROMPT)

    def test_first_settle_is_distinct_from_end_residual_and_invalid_values(self):
        records = [dict(time_to_settle_ms=100, remaining_error_deg=3.4),
                   dict(time_to_settle_ms=None, remaining_error_deg=.05),
                   dict(time_to_settle_ms=float('nan'), remaining_error_deg=1)]
        summary = prepare_session(dict(aim_corrections=records))['aim_correction_summary']
        self.assertEqual(summary['settled_acquisitions'], 1)
        self.assertEqual(summary['ended_on_target_acquisitions'], 1)
        self.assertEqual(summary['mean_time_to_settle_ms'], 100)

    def test_measured_summary_replaces_invented_ai_summary(self):
        from coach_app.report_format import complete_report
        report = complete_report('Session Summary: invented accuracy 100%\nStrengths: Evidence limited.\nWeaknesses: Tracking can move.\nNext Drill: Take 20 shots.',
            dict(shots=135, hits=121, misses=14, accuracy=89.6296, avg_reaction_ms=839,
                 aim_corrections=[dict(time_to_settle_ms=200, remaining_error_deg=3.4)]), require_ai=True)
        self.assertNotIn('invented', report)
        self.assertIn('89.6%', report)
        self.assertNotIn('reached <=0.1', report)
        self.assertIn('average gap still left when help ended was 3.400 deg', report)

    def test_player_summary_explains_gap_and_keeps_counts_consistent(self):
        from coach_app.report_format import complete_report
        session = dict(shots=41, hits=40, misses=1, accuracy=97.6, avg_reaction_ms=1837,
                       aim_corrections=[dict(initial_error_deg=1.117, remaining_error_deg=.317)])
        result = complete_report('', session)
        self.assertIn('before help and 0.317 deg when help ended', result)
        self.assertIn('do not measure unaided aim', result)
        self.assertNotIn('Mean entry error:', result)
        self.assertEqual(prepare_session(session)['aim_correction_summary']['not_ended_on_target_acquisitions'], 1)

    def test_real_drill_is_not_cut_at_48_words_or_rounded(self):
        from coach_app.report_format import complete_report
        drill = ("Keep the same target mode and turn assistance off. Fire twenty deliberate shots, "
                 "taking time to place the crosshair on the head before each shot. "
                 "Then compare your unassisted hit rate with this assisted session. "
                 "This comparison helps separate manual alignment from help supplied by the assistant. "
                 "Record the result before changing settings.")
        report = complete_report('Session Summary: Data.\nStrengths: Average gap 0.306 degrees.\nWeaknesses: Manual skill is unmeasured.\nNext Drill: '+drill, {}, require_ai=True)
        self.assertTrue(report.endswith(drill))
        self.assertIn('0.306', report)
        self.assertNotIn('...', report)
