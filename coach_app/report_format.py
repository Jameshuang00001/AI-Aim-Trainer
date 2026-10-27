"""Compact model input and complete, bounded plain-text coach reports."""

import math
import re
from statistics import median, quantiles
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


def hit_timing_summary(session):
    values = sorted(number(x.get("reaction_ms")) for x in session.get("shots_detail", [])
                    if isinstance(x, dict) and x.get("hit") is True and number(x.get("reaction_ms")) > 0)
    if len(values) < 10:
        return None
    lower, _, upper = quantiles(values, n=4, method="inclusive")
    return {"count": len(values), "median": median(values), "lower": lower, "upper": upper}


# Eligibility and rationale are computed locally; the model chooses among these only.
def drill_options(session):
    data = prepare_session(session)
    shots, hits, misses = data["shots"], data["hits"], data["misses"]
    correction = data.get("aim_correction_summary", {})
    assisted = correction.get("acquisitions", 0) > 0
    prefix = "Keep the same target mode and sensitivity. Start a fresh session with assistance off. "
    options = {}
    def add(key, evidence, instruction):
        options[key] = {"evidence": evidence, "instruction": prefix + instruction}
    if shots < 20:
        add("baseline", f"Only {shots} shots are recorded; a longer manual sample is useful before choosing a narrower exercise.",
            "Take 20 deliberate shots. Record accuracy and average target-to-hit time as a manual baseline; this time includes finding and aiming at targets.")
    if assisted:
        entry, end = correction.get("mean_entry_error_deg"), correction.get("mean_residual_deg")
        evidence = f"This session contains {correction['acquisitions']} assistance segments, so its accuracy includes help."
        if entry is not None and end is not None:
            evidence += f" Mean gap was {entry:.3f} deg before help and {end:.3f} deg when help ended."
        add("assist_comparison", evidence,
            "Take 20 shots. Compare hit rate with this assisted session to see how results differ without help. Do not compare correction errors: they are not recorded when assistance is off. This is a new manual reference, not proof of improvement.")
    if misses > 0:
        add("deliberate_shots", f"{misses} of {shots} shots missed. The records do not identify why.",
            "Take 20 single shots, confirming the crosshair is on the target before clicking. Record misses per 20 shots and average target-to-hit time. Prioritize fewer misses while allowing more aiming time. This tests a deliberate approach, not a diagnosed cause.")
    if assisted and correction.get("acquisitions", 0) >= 10 and correction.get("mean_entry_error_deg") is not None and correction["mean_entry_error_deg"] >= 2:
        add("manual_landing", f"Across {correction['acquisitions']} assistance segments, the mean gap at assist start was {correction['mean_entry_error_deg']:.3f} deg. That measures the starting gap, not its cause or unaided shot error.",
            "For this exercise, choose Static Targets in Settings. Take 20 single shots without assistance, placing the crosshair on each visible target before firing. Record accuracy and target-to-hit time as a new static manual reference. This practices closing the gap yourself; do not compare unrecorded manual angular errors or treat a change of mode as a matched comparison.")
    timing = hit_timing_summary(session)
    if not assisted and timing:
        middle, slow, fast = timing["median"], timing["upper"], timing["lower"]
        if fast > 0 and slow >= fast * 1.5:
            add("steady_acquisition", f"Across {timing['count']} timed hits, the middle half spans {fast:.0f}–{slow:.0f} ms; acquisition time varies. The cause is unknown.",
                "Take 20 shots with a repeatable sequence: find the target, align, then click. Avoid imposing a fixed firing interval. Compare the spread of timed hits in the next report, alongside accuracy; do not trade accuracy for speed.")
        if shots >= 20 and hits / max(shots, 1) >= .9:
            add("controlled_pace", f"You hit {hits}/{shots} shots without recorded assistance. Median target-to-hit time was {middle:.0f} ms across {timing['count']} timed hits.",
                "Take 20 shots, aiming to acquire targets a little sooner while keeping at least this session's hit rate. Compare accuracy and median target-to-hit time in the next report. If accuracy falls, return to a deliberate pace; this is an experiment, not a claim that your reactions are slow.")
    if not options:
        add("baseline", f"This session records {shots} shots. No more specific supported exercise is eligible.",
            "Take 20 deliberate shots and record accuracy and average target-to-hit time as a manual reference.")
    return options


def allowed_drills(session):
    return {key: value["instruction"] for key, value in drill_options(session).items()}


def checked_drill(response, session):
    import json
    choice = json.loads(response)
    if not isinstance(choice, dict) or set(choice) != {"drill_id"}:
        raise ValueError("Expected only drill_id")
    drill_id = choice["drill_id"]
    if not isinstance(drill_id, str) or drill_id not in allowed_drills(session):
        raise ValueError("Unsupported drill or missing session evidence")
    return drill_id


def measured_report(session, drill_id=None, source=None):
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
    options = drill_options(session)
    drills = allowed_drills(session)
    if drill_id is not None and drill_id not in drills:
        raise ValueError("Drill does not match session evidence")
    drill = ("AI-selected, program-checked exercise: " + drills[drill_id] + "\n\nWhy this exercise:\n" + options[drill_id]["evidence"] if drill_id else
             "No validated AI exercise is available. The measurements and explanations above are still available; retry analysis for a suggestion.")
    timing = hit_timing_summary(session)
    if timing:
        observation += (f" Across {timing['count']} timed hits, median target-to-hit time was {timing['median']:.0f} ms; "
                        f"the middle half was {timing['lower']:.0f}–{timing['upper']:.0f} ms.")
    return (("Analysis source: " + source + "\n\n" if source else "") + "Session Summary:\n" + "\n".join(summary) + "\n\nWhat the data shows:\n" + observation +
            "\n\nWhat it cannot tell us:\n" + limitation + "\n\nNext Drill:\n" + drill)


def session_comparison(session, previous=None):
    """Measured changes, not a claim that two training conditions were matched."""
    if not previous:
        return {"available": False, "explanation": "No earlier completed session is available in this session folder."}
    current_shots, previous_shots = number(session.get("shots")), number(previous.get("shots"))
    if current_shots <= 0 or previous_shots <= 0:
        return {"available": False, "explanation": "Both sessions need shots before accuracy can be compared."}
    current_hits, previous_hits = number(session.get("hits")), number(previous.get("hits"))
    if not (0 <= current_hits <= current_shots and 0 <= previous_hits <= previous_shots):
        return {"available": False, "explanation": "Shot counts are inconsistent; comparison is unavailable."}
    before = previous_hits / previous_shots * 100
    after = current_hits / current_shots * 100
    delta = after - before
    change = "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"
    text = (f"Accuracy {change}: {before:.1f}% ({int(previous_hits)}/{int(previous_shots)}) in the previous session "
            f"to {after:.1f}% ({int(current_hits)}/{int(current_shots)}) now; change {delta:+.1f} percentage points.")
    previous_assist = bool(previous.get("aim_corrections"))
    current_assist = bool(session.get("aim_corrections"))
    if previous_assist != current_assist:
        text += " Assistance use differs between sessions, so this is not a like-for-like manual comparison."
    if min(current_shots, previous_shots) < 20:
        text += " At least one session has fewer than 20 shots; the difference may reflect a small sample."
    text += " Target mode and sensitivity were not saved in these exports, so matched conditions and skill improvement cannot be established."
    return {"available": True, "previous_shots": int(previous_shots), "previous_hits": int(previous_hits),
            "previous_accuracy": round(before, 3), "current_accuracy": round(after, 3),
            "accuracy_change_percentage_points": round(delta, 3),
            "previous_assistance_recorded": previous_assist, "current_assistance_recorded": current_assist,
            "previous_avg_target_to_hit_ms": number(previous.get("avg_reaction_ms")),
            "current_avg_target_to_hit_ms": number(session.get("avg_reaction_ms")), "explanation": text}


def checked_coaching(response):
    """Light structural checks; wording and exercise choice belong to the model."""
    import json
    value = json.loads(response)
    required = {"feedback", "possible_reason", "next_drill"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Expected feedback, possible_reason and next_drill")
    for key in required:
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 2200:
            raise ValueError("Incomplete or oversized coaching text")
    return {key: value[key].strip() for key in required}


def conversational_report(session, notes, previous=None, source=None):
    # Preserve measured facts, replace repetitive stock interpretation with AI prose.
    summary = "\n".join(parse_sections(complete_report("", session))["Session Summary"])
    comparison = session_comparison(session, previous)
    return (("Analysis source: " + source + "\n\n" if source else "") +
            "Session Summary:\n" + summary + "\n\nCompared with your previous session:\n" + comparison["explanation"] +
            "\n\nCoach feedback (AI interpretation):\n" + notes["feedback"] +
            "\n\nPossible explanation (hypothesis, not a measured cause):\n" + notes["possible_reason"] +
            "\n\nTry this next (AI suggestion):\n" + notes["next_drill"])
