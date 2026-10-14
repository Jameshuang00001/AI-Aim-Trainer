"""Offline tests: no API credentials or paid requests are used."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from coach_app import nebius_client as coach


class NebiusClientTests(unittest.TestCase):
    def test_missing_key_uses_labeled_demo(self):
        with patch.dict("os.environ", {}, clear=True):
            report = coach.analyze_session({"shots": 2})
        self.assertIn(coach.MISSING_KEY_MESSAGE, report)
        self.assertIn("Demo report", report)

    def test_model_order_and_fallbacks(self):
        for index, expected in enumerate(coach.MODEL_PREFERENCES):
            client = MagicMock()
            client.models.list.return_value = [
                SimpleNamespace(id=model) for model in reversed(coach.MODEL_PREFERENCES[index:])
            ]
            self.assertEqual(coach.check_model_availability(client), expected)

    def test_no_available_model(self):
        client = MagicMock()
        client.models.list.return_value = []
        with self.assertRaises(coach.AnalysisError):
            coach.check_model_availability(client)

    def test_real_analysis_request(self):
        client = MagicMock()
        client.models.list.return_value = [SimpleNamespace(id=coach.MODEL_PREFERENCES[0])]
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="# Strengths\nEvidence"))]
        )
        factory = MagicMock()
        factory.return_value.__enter__.return_value = client
        session = {"shots": 2, "hits": 1, "shots_detail": [{"t_ms": 42, "hit": True}]}
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-placeholder"}, clear=True):
            with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}):
                self.assertEqual(coach.analyze_session(session), "# Strengths\nEvidence")
        self.assertEqual(factory.call_args.kwargs["base_url"], coach.BASE_URL)
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], coach.MODEL_PREFERENCES[0])
        self.assertEqual(request["messages"][0]["content"], coach.SYSTEM_PROMPT)
        self.assertEqual(json.loads(request["messages"][1]["content"].split("\n", 1)[1]), session)

    def test_api_failure_does_not_use_demo_or_expose_key(self):
        factory = MagicMock(side_effect=RuntimeError("secret-test-key"))
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "secret-test-key"}, clear=True):
            with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}):
                with self.assertRaises(coach.AnalysisError) as result:
                    coach.analyze_session({})
        self.assertNotIn("secret-test-key", str(result.exception))


if __name__ == "__main__":
    unittest.main()
