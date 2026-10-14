# Session JSON Export

Opening SummaryPanel exports current stats to
Application.persistentDataPath/session_logs/<session_id>.json. The folder is
created automatically and the saved absolute path is printed to the Console.
No Inspector setup, screen capture, or additional JSON package is required.

Each stats reset starts a new ID and recording. Reopening the resumable summary
updates the same session file with all shots so far, rather than creating duplicate
files. It does not reset scores, remove targets, or alter existing pause/input UI.
The latest summary view supplies ended_at; practice may continue afterward.

Schema conventions (SPEC.pdf was not present in the workspace):

- session_id: unique GUID string.
- started_at / ended_at: UTC ISO 8601 strings.
- shots / hits / misses: current integer counters.
- accuracy: percentage from 0 to 100, matching the HUD.
- avg_reaction_ms: existing average reaction time converted to milliseconds.
- shots_detail: one entry per registered shot.
- t_ms: elapsed real milliseconds since recording started, including menu pauses.
- hit: true only for an accepted target hit; false for misses and early shots.
- target_id: stable ID for the target instance, included when available.
- reaction_ms: included for accepted hits only; early shots do not record it.

No mode field is exported; the coach app is responsible for tagging mode.
Writes use a temporary file and replacement to avoid leaving partial JSON at
the final filename. Errors log to Console without interrupting the summary.

Play-mode checks: shoot one valid hit, one empty-space miss, and one early
reaction miss. Open summary and inspect its path: counters should match the HUD,
detail count should match shots, and only accepted hits have reaction_ms.
Close and reopen summary after more shots: same path, updated totals. Change mode
or time limit to reset stats: the next summary should produce a new session ID.
