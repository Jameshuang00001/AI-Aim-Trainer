"""Nebius Token Factory analysis; credentials come only from the environment."""

import json
import os
from typing import Any

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
MODEL_PREFERENCES = (
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Nemotron-3_5-Lightning",
    "nvidia/nemotron-3-super-120b-a12b",
)
MISSING_KEY_MESSAGE = "NEBIUS_API_KEY is not set. Please set it before running AI analysis."
SYSTEM_PROMPT = (
    "You are an FPS aim coach. Analyze the player's session results "
    "(accuracy, reaction time, per-shot data). Give: 2 strengths, "
    "2 weaknesses with evidence, one focused drill for next session. "
    "Be specific, cite numbers, no generic advice."
)


class AnalysisError(RuntimeError):
    """Safe user-facing error, without credential or request-body disclosure."""


def check_model_availability(client: Any) -> str:
    """Query the actual account catalog before choosing a preferred model."""
    available = {model.id for model in client.models.list()}
    for model in MODEL_PREFERENCES:
        if model in available:
            return model
    raise AnalysisError("None of the preferred Nebius models is available for this API key.")


def analyze_session(session_json: dict[str, Any]) -> str:
    api_key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not api_key:
        return MISSING_KEY_MESSAGE + "\n\n" + fake_report(session_json)
    try:
        from openai import OpenAI
    except ImportError as error:
        raise AnalysisError("Install coach_app/requirements.txt to enable Nebius analysis.") from error
    try:
        with OpenAI(api_key=api_key, base_url=BASE_URL, timeout=60.0, max_retries=1) as client:
            model = check_model_availability(client)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Analyze this Unity session JSON:\n" +
                     json.dumps(session_json, ensure_ascii=False, allow_nan=False)},
                ],
                max_tokens=3000,
            )
            report = response.choices[0].message.content
            if not report or not report.strip():
                raise AnalysisError("Nebius returned an empty report. Please try again.")
            return report
    except AnalysisError:
        raise
    except Exception as error:
        # Do not expose raw SDK errors, headers, keys, or session JSON in the UI.
        status = getattr(error, "status_code", None)
        if status in (401, 403):
            message = "Nebius authentication or access failed. Check NEBIUS_API_KEY and account permissions."
        elif status == 429:
            message = "Nebius rate limit reached. Please try again later."
        else:
            message = "Nebius analysis failed. Check your connection, account access, and model availability, then retry."
        raise AnalysisError(message) from error


def fake_report(session_json: dict[str, Any]) -> str:
    return (
        "# Practice Report\n\n"
        "**Demo report: no AI analysis has been performed.**\n\n"
        f"- Shots: {session_json.get('shots', 0)}\n"
        f"- Hits: {session_json.get('hits', 0)}\n"
        f"- Misses: {session_json.get('misses', 0)}\n"
        f"- Accuracy: {session_json.get('accuracy', 0)}%\n"
        f"- Average reaction: {session_json.get('avg_reaction_ms', 0)} ms\n\n"
        "## Practice Focus\n\n"
        "Use consistent practice blocks and compare your next session.\n"
    )
