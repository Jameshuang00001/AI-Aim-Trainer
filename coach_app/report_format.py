"""Compact model input and complete, bounded plain-text coach reports."""

import math
import re
from typing import Any

SECTIONS = ("Session Summary", "Strengths", "Weaknesses", "Next Drill")


def number(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def prepare_session(session: dict[str, Any]) -> dict[str, Any]:
    def clean(value, key=""):
        if key in ("shots", "hits", "misses", "t_ms", "reaction_ms"):
            return round(number(value))
        if key == "accuracy":
            return f"{number(value):.1f}%"
        if key in ("avg_reaction_ms", "fastest_reaction_ms"):
            return f"{round(number(value))} ms"
        if isinstance(value, dict):
            return {name: clean(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, float):
            return round(number(value), 1)
        return value

    prepared = clean(session)
    for key in ("shots", "hits", "misses", "accuracy", "avg_reaction_ms"):
        prepared[key] = clean(session.get(key, 0), key)
    reactions = [number(shot["reaction_ms"]) for shot in session.get("shots_detail", [])
                 if isinstance(shot, dict) and shot.get("hit") is True
                 and shot.get("reaction_ms") is not None and number(shot["reaction_ms"]) >= 0]
    prepared["fastest_reaction_ms"] = f"{round(min(reactions))} ms" if reactions else "Unavailable"
    if isinstance(session.get("aim_corrections"), list):
        records = [item for item in session["aim_corrections"] if isinstance(item, dict)]
        settled = [item for item in records if number(item.get("time_to_settle_ms", -1)) >= 0]
        def mean(items, key):
            values = []
            for item in items:
                try: value = float(item[key])
                except (KeyError, TypeError, ValueError): continue
                if math.isfinite(value): values.append(value)
            return round(sum(values) / len(values), 3) if values else None
        prepared["aim_correction_summary"] = {
            "acquisitions": len(records), "settled_acquisitions": len(settled),
            "mean_entry_error_deg": mean(records, "initial_error_deg"),
            "mean_residual_deg": mean(records, "remaining_error_deg"),
            "mean_applied_path_deg": mean(records, "path_length_deg"),
            "mean_duration_ms": mean(records, "duration_ms"),
            "mean_time_to_settle_ms": mean(settled, "time_to_settle_ms"),
            "mean_speed_deg_per_second": mean(records, "speed_deg_per_second"),
            "mean_signed_yaw_error_deg": mean(records, "initial_yaw_error_deg"),
            "mean_signed_pitch_error_deg": mean(records, "initial_pitch_error_deg"),
        }
    return prepared


def parse_sections(report: str) -> dict[str, list[str]]:
    content = {section: [] for section in SECTIONS}
    current = None
    # Accept numbered, bold, and Markdown headings without treating prose as one.
    heading = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s*)?(?:\*\*)?(Session Summary|Strengths|Weaknesses|Next Drill)(?:\*\*)?\s*:?(?:\*\*)?\s*(.*)$", re.I)
    report = re.sub(r"<think>.*?</think>", "", report, flags=re.S)
    if "<think>" in report:  # Unfinished reasoning is not a final coach report.
        report = report.split("<think>", 1)[0]
    for line in report.splitlines():
        match = heading.match(line)
        if match:
            current = next(section for section in SECTIONS if section.lower() == match[1].lower())
            if match[2].strip():
                content[current].append(match[2].strip())
        elif current and line.strip() and "|" not in line and not line.strip().startswith("```"):
            content[current].append(line.strip())
    return content


def complete_report(report: str, session: dict[str, Any], require_ai: bool = False) -> str:
    data = prepare_session(session)
    summary = (
        f"- {data['shots']} shots, {data['hits']} hits, {data['misses']} misses, "
        f"{data['accuracy']} accuracy.\n- Average reaction: {data['avg_reaction_ms']}."
    )
    if data["shots"] < 10:
        summary += "\n- Small sample size; conclusions are tentative."
    defaults = {
        "Session Summary": summary,
        "Strengths": f"- Local fallback: {data['hits']} valid hits recorded.",
        "Weaknesses": f"- Local fallback: {data['misses']} misses recorded; more data is needed to explain their cause.",
        "Next Drill": "- Local fallback: take 20 deliberate single shots. Recenter after each shot and compare accuracy.",
    }
    content = parse_sections(report)
    missing = [section for section in SECTIONS if not content[section]]
    if require_ai and missing:
        raise ValueError("AI report missing sections: " + ", ".join(missing))

    output = []
    for section in SECTIONS:
        text = "\n".join(content[section]) or defaults[section]
        # The measured summary is always built locally, avoiding precision drift.
        if section == "Session Summary" and not require_ai:
            text = summary
        text = re.sub(r"(-?\d+\.\d+)\s*ms\b", lambda m: f"{round(float(m[1]))} ms", text)
        text = re.sub(r"-?\d+\.\d{2,}", lambda m: f"{float(m[0]):.1f}", text)
        text = text.replace("**", "")
        # Budget each section independently so no required section is cut off.
        words = text.split()
        if len(words) > 48:
            text = " ".join(words[:47]) + "..."
        output.append(section + ":\n" + text)
    return "\n\n".join(output)
