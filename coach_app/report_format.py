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
        def finite(item, key):
            try: value = float(item[key])
            except (KeyError, TypeError, ValueError): return None
            return value if math.isfinite(value) else None
        settled = [item for item in records
                   if (value := finite(item, "time_to_settle_ms")) is not None and value >= 0]
        ended_on_target = [item for item in records
                           if (value := finite(item, "remaining_error_deg")) is not None and 0 <= value <= 0.1]
        def mean(items, key):
            values = []
            for item in items:
                try: value = float(item[key])
                except (KeyError, TypeError, ValueError): continue
                if math.isfinite(value): values.append(value)
            return round(sum(values) / len(values), 3) if values else None
        prepared["aim_correction_summary"] = {
            "acquisitions": len(records), "settled_acquisitions": len(settled),
            "ended_on_target_acquisitions": len(ended_on_target),
            "not_ended_on_target_acquisitions": len(records) - len(ended_on_target),
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
    correction = data.get("aim_correction_summary", {})
    if correction.get("acquisitions"):
        summary += "\n- Assistance was used, so these hits do not measure unaided aim."
        entry = correction["mean_entry_error_deg"]
        residual = correction["mean_residual_deg"]
        if entry is not None and residual is not None:
            summary += (f"\n- Across {correction['acquisitions']} corrections, the average gap from the head "
                        f"was {entry:.3f} deg before help and {residual:.3f} deg when help ended.")
        elif residual is not None:
            summary += f"\n- The average gap still left when help ended was {residual:.3f} deg."
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
        if section == "Session Summary":
            text = summary
        text = re.sub(r"(-?\d+\.\d+)\s*ms\b", lambda m: f"{round(float(m[1]))} ms", text)
        if section != "Session Summary" and not require_ai:
            text = re.sub(r"-?\d+\.\d{2,}", lambda m: f"{float(m[0]):.1f}", text)
        text = text.replace("**", "")
        # Real AI reports are length-checked and retried upstream, never cut mid-instruction.
        # Keep the offline/demo formatter bounded.
        words = text.split()
        if not require_ai and section != "Session Summary" and len(words) > 48:
            text = " ".join(words[:47]) + "..."
        output.append(section + ":\n" + text)
    return "\n\n".join(output)


# Only these drills can reach the UI. AI selects an eligible ID; it cannot write claims.
def allowed_drills(session):
    data = prepare_session(session)
    drills = {"baseline": "Keep the same target mode and sensitivity. Turn assistance off and take 20 deliberate shots. Record accuracy and average target-to-hit time as a manual baseline; this time includes finding and aiming at targets."}
    if data.get("aim_correction_summary", {}).get("acquisitions", 0):
        drills["assist_comparison"] = "Keep the same target mode and sensitivity. Start a fresh session with assistance off and take 20 shots. Compare hit rate with this assisted session to see how results differ without help. Do not compare correction errors: they are not recorded when assistance is off."
    if data["misses"] > 0:
        drills["deliberate_shots"] = "Keep the same target mode and sensitivity, turn assistance off, and take 20 single shots. Place the crosshair on the head before each click. Compare misses and average target-to-hit time with this session; this tests a more deliberate approach, not a diagnosed cause of the misses."
    return drills


def checked_drill(response, session):
    import json
    choice = json.loads(response)
    if not isinstance(choice, dict) or set(choice) != {"drill_id"}:
        raise ValueError("Expected only drill_id")
    drill_id = choice["drill_id"]
    if not isinstance(drill_id, str) or drill_id not in allowed_drills(session):
        raise ValueError("Unsupported drill or missing session evidence")
    return drill_id


def measured_report(session, drill_id=None):
    """All prose is locally grounded; no free-form model text is rendered."""
    data = prepare_session(session)
    # Reuse only the deterministic summary, never model-supplied interpretation.
    summary = parse_sections(complete_report("", session))["Session Summary"]
    correction = data.get("aim_correction_summary", {})
    count = correction.get("acquisitions", 0)
    if count:
        entry, end = correction["mean_entry_error_deg"], correction["mean_residual_deg"]
        if entry is not None and end is not None:
            relation = "smaller" if end < entry else "larger" if end > entry else "unchanged"
            observation = (f"The average gap from the head was {relation} when assistance ended "
                           f"({entry:.3f} to {end:.3f} deg). This describes assisted alignment, not improvement in manual skill.")
        else:
            observation = "Assistance was recorded, but some angle measurements are missing; its before-and-after gap cannot be compared."
        limitation = ("The remaining gap is measured when each correction stops, not at each shot. "
                      "It cannot tell us whether you overshot, stopped early, or followed a moving target. "
                      "These averages do not establish consistent aim or a good/bad skill rating.")
    else:
        observation = (f"You hit {data['hits']} of {data['shots']} shots. This records this session's outcome, "
                       "not improvement over earlier sessions.")
        limitation = ("No correction measurements are available. Hits and misses alone cannot explain aim direction or the cause of a miss. "
                      "Average target-to-hit time includes searching and aiming; it is not a pure reflex test.")
    drills = allowed_drills(session)
    if drill_id is not None and drill_id not in drills:
        raise ValueError("Drill does not match session evidence")
    drill = ("AI-selected, program-checked exercise: " + drills[drill_id] if drill_id else
             "No validated AI exercise is available. The measurements and explanations above are still available; retry analysis for a suggestion.")
    return ("Session Summary:\n" + "\n".join(summary) + "\n\nWhat the data shows:\n" + observation +
            "\n\nWhat it cannot tell us:\n" + limitation + "\n\nNext Drill:\n" + drill)
