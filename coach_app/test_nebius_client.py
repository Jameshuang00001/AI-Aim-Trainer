"""Offline tests: no API credentials or paid requests are used."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from coach_app import nebius_client as coach


class NebiusClientTests(unittest.TestCase):
    def test_both_mode_prompts_require_english(self):
        rule = ("Respond in English only. Do not switch languages. "
                "All section headings, explanations, and training "
                "recommendations must be written in natural English.")
        for prompt in (coach.SYSTEM_PROMPT, coach.MODE_1_SYSTEM_PROMPT, coach.MODE_2_SYSTEM_PROMPT):
            self.assertIn(rule, prompt)
            for heading in ("Session Summary:", "Strengths:", "Weaknesses:", "Next Drill:"):
                self.assertIn(heading, prompt)

    def test_missing_key_is_an_explicit_error(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(coach.AnalysisError, "NEBIUS_API_KEY is not set"):
                coach.analyze_session({"shots": 2})

    def test_demo_large_sample_has_no_small_sample_warning(self):
        self.assertNotIn("Small sample size", coach.fake_report({"shots": 10}))

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
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=
                "Session Summary:\n- 2 shots.\nStrengths:\n- One hit.\nWeaknesses:\n- Small sample.\nNext Drill:\n- Take 20 shots."))]
        )
        factory = MagicMock()
        factory.return_value.__enter__.return_value = client
        session = {"shots": 2, "hits": 1, "shots_detail": [{"t_ms": 42, "hit": True}]}
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test-placeholder"}, clear=True):
            with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}):
                report = coach.analyze_session(session)
                self.assertIn("Strengths:\n- One hit.", report)
                self.assertNotIn("Local fallback", report)
                self.assertIn("Next Drill:", report)
        self.assertEqual(factory.call_args.kwargs["base_url"], coach.BASE_URL)
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], coach.MODEL_PREFERENCES[0])
        self.assertEqual(request["messages"][0]["content"], coach.SYSTEM_PROMPT)
        self.assertFalse(request["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(json.loads(request["messages"][1]["content"].split("\n", 1)[1]), coach.prepare_session(session))

    def test_precise_format_and_fastest_valid_hit(self):
        session = dict(shots=24.0, hits=17.0, misses=7.0, accuracy=70.83333587646484,
                       avg_reaction_ms=1138.7275390625,
                       shots_detail=[{"hit": True, "reaction_ms": 482.7},
                                     {"hit": False, "reaction_ms": 1}])
        data = coach.prepare_session(session)
        self.assertEqual(data["accuracy"], "70.8%")
        self.assertEqual(data["avg_reaction_ms"], "1139 ms")
        self.assertEqual(data["fastest_reaction_ms"], "483 ms")
        self.assertIsInstance(data["shots"], int)
        self.assertEqual(session["accuracy"], 70.83333587646484)

    def test_empty_or_long_reports_keep_all_sections(self):
        for text in ("", "Strengths:\n" + "word " * 500 + "\nWeaknesses:\n| bad | table |"):
            result = coach.complete_report(text, {"shots": 2})
            for section in ("Session Summary:", "Strengths:", "Weaknesses:", "Next Drill:"):
                self.assertEqual(result.count(section), 1)
            self.assertLess(len(result.split()), 250)
            self.assertNotIn("|", result)
            self.assertIn("Small sample size", result)

    def test_api_failure_does_not_use_demo_or_expose_key(self):
        factory = MagicMock(side_effect=RuntimeError("secret-test-key"))
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "secret-test-key"}, clear=True):
            with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}):
                with self.assertRaises(coach.AnalysisError) as result:
                    coach.analyze_session({})
        self.assertNotIn("secret-test-key", str(result.exception))

    def test_truncated_response_retries_then_errors_without_fallback(self):
        client = MagicMock()
        client.models.list.return_value = [SimpleNamespace(id=coach.MODEL_PREFERENCES[0])]
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content=""))])
        factory = MagicMock()
        factory.return_value.__enter__.return_value = client
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "test"}, clear=True):
            with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=factory)}):
                with self.assertRaisesRegex(coach.AnalysisError, "max_tokens exhausted"):
                    coach.analyze_session({})
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_numbered_headings_and_strict_missing_section(self):
        from coach_app.report_format import parse_sections
        self.assertEqual(parse_sections("### 2. **Strengths:**\n- Evidence")["Strengths"], ["- Evidence"])
        with self.assertRaisesRegex(ValueError, "missing sections"):
            coach.complete_report("Strengths:\n- Evidence", {}, require_ai=True)


if __name__ == "__main__":
    unittest.main()
