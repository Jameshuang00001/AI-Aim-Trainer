"""Offline request/validation tests; no credentials or paid calls."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from coach_app import nebius_client as coach
from coach_app.report_format import checked_drill, measured_report, allowed_drills

class NebiusClientTests(unittest.TestCase):
    def run_model(self, replies, session=None):
        factory = MagicMock()
        client = factory.return_value.__enter__.return_value
        client.models.list.return_value = [SimpleNamespace(id=coach.MODEL_PREFERENCES[0])]
        client.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content=text))]) for text, reason in replies]
        with patch('coach_app.nebius_client.get_api_key', return_value='mock-secret'), patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=factory)}):
            result = coach.analyze_session(session or {})
        return result, client

    def test_valid_selection_renders_only_local_words(self):
        session = dict(shots=57, hits=55, misses=2, accuracy=96.5, avg_reaction_ms=1141,
                       aim_corrections=[dict(initial_error_deg=4.312, remaining_error_deg=1.105)])
        report, client = self.run_model([('{"drill_id":"assist_comparison"}', 'stop')], session)
        self.assertIn('4.312 to 1.105 deg', report)
        self.assertIn('not improvement in manual skill', report)
        self.assertIn('Do not compare correction errors', report)
        self.assertNotIn('stable settling', report)
        request = client.chat.completions.create.call_args.kwargs
        payload = json.loads(request['messages'][1]['content'].split('\n', 1)[1])
        self.assertEqual(payload['allowed_drills'], allowed_drills(session))
        self.assertFalse(request['extra_body']['chat_template_kwargs']['enable_thinking'])

    def test_bad_advice_retries_then_does_not_leak(self):
        bad = '{"drill_id":"baseline","advice":"You have precise hand-eye coordination"}'
        report, client = self.run_model([(bad, 'stop'), (bad, 'stop')])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertIn('No validated AI exercise', report)
        self.assertNotIn('precise hand-eye', report)
        self.assertIn('Session Summary:', report)

    def test_retry_can_recover(self):
        report, client = self.run_model([('Shoot those historical targets...', 'stop'), ('{"drill_id":"baseline"}', 'stop')])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertIn('AI-selected, program-checked', report)

    def test_truncated_valid_json_is_rejected(self):
        report, _ = self.run_model([('{"drill_id":"baseline"}', 'length')]*2)
        self.assertIn('No validated AI exercise', report)

    def test_drills_require_evidence_and_exact_schema(self):
        for response in ['{"drill_id":"assist_comparison"}', '{"drill_id":"deliberate_shots"}',
                         '{"drill_id":"replay_target"}', '[]', '{"drill_id":3}',
                         '{"drill_id":"baseline","extra":"made-up claim"}']:
            with self.assertRaises(ValueError): checked_drill(response, {})
        self.assertEqual(checked_drill('{"drill_id":"deliberate_shots"}', {'misses':1}), 'deliberate_shots')

    def test_end_gap_does_not_imply_stability_or_skill(self):
        for entry, end, expected in [(1,2,'larger'), (2,1,'smaller'), (1,1,'unchanged')]:
            report = measured_report({'aim_corrections':[dict(initial_error_deg=entry, remaining_error_deg=end)]})
            self.assertIn('was '+expected, report)
            self.assertIn('not improvement in manual skill', report)
        self.assertIn('measurements are missing', measured_report({'aim_corrections':[{}]}))

    def test_missing_key_is_explicit(self):
        with patch('coach_app.nebius_client.get_api_key', return_value=None):
            with self.assertRaisesRegex(coach.AnalysisError, 'NEBIUS_API_KEY'): coach.analyze_session({})

    def test_api_failure_does_not_expose_secret(self):
        with patch('coach_app.nebius_client.get_api_key', return_value='secret'), patch.dict('sys.modules', {'openai':SimpleNamespace(OpenAI=MagicMock(side_effect=RuntimeError('secret')))}):
            with self.assertRaises(coach.AnalysisError) as result: coach.analyze_session({})
        self.assertNotIn('secret', str(result.exception))

    def test_model_order(self):
        for index, model in enumerate(coach.MODEL_PREFERENCES):
            client = MagicMock()
            client.models.list.return_value = [SimpleNamespace(id=x) for x in reversed(coach.MODEL_PREFERENCES[index:])]
            self.assertEqual(coach.check_model_availability(client), model)
        client.models.list.return_value = []
        with self.assertRaises(coach.AnalysisError): coach.check_model_availability(client)

    def test_demo_does_not_claim_ai_selection(self):
        result = coach.fake_report({'shots':20})
        self.assertIn('no AI analysis', result)
        self.assertNotIn('AI-selected', result)
