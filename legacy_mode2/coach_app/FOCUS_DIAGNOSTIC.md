# Fresh foreground query and passive focus-switch test

## Cause and fix

The command-line matrix previously polled
`NSWorkspace.sharedWorkspace().frontmostApplication()` without letting Cocoa's
main run loop process workspace notifications. Its value stayed at the Terminal
PID captured at startup even while fresh Unity gameplay telemetry changed.
This is strong evidence for stale workspace state, not proof that a visible
Unity window was foreground.

Apple documents main-run-loop-dependent updates to application state:
https://developer.apple.com/documentation/appkit/nsrunningapplication

The matrix now uses `ForegroundQuery`: on the main thread, read NSWorkspace,
service its main run loop for a bounded turn, then read it again. The returned
foreground PID is the **after-pump** value. Both values and query timestamps
are logged. Missing results or query errors fail closed; there is no fallback
to the before-pump value or the selected window's owner. The time taken to
process notifications is included in the existing 200 ms telemetry-age check.
No activation, focus-forcing, window raising, or input posting is involved.

Other guards, UDP 8767, event construction/dispatch and F8 remain unchanged.
No Coach.app rebuild is needed for this command-line tool change. The fix does
not enable Head Lock or change the packaged Coach's separate input worker.

## Actual local verification: 2026-10-22

The user physically switched apps while the passive observer ran. Local
America/Toronto times and actual PIDs:

| Time | Before Cocoa turn | After Cocoa turn (used by validation) |
| --- | --- | --- |
| 19:45:59.443 | Codex 66185 | Terminal 64533 |
| 19:46:02.228 | Terminal 64533 | Unity standalone 66661 |
| 19:46:07.378 | Unity standalone 66661 | Terminal 64533 |
| 19:46:13.264 | Terminal 64533 | Unity standalone 66661 |

The required Terminal -> Unity -> Terminal sequence was observed.
`sequence_verified=true`, `stale_value_observed=true`, `error=null`.
The before/after mismatches directly reproduce stale workspace state and show
that processing the main run loop refreshes it on this machine.

Full timestamped log:
`/Users/james/Library/Logs/AI-Aim-Trainer/focus_diagnostics/assist-5c6bbdedb1524be9bfc15e9355115831.jsonl`

`input_events_posted=false`, `head_lock_enabled=false`. The observer did not
activate windows or read/occupy UDP 8767. This confirms the foreground-query
fix, **not** synthetic input acceptance or successful camera calibration.

## Live verification (requires physical user switching)

From the project root, substitute current IDs:

```sh
.venv/bin/python -m coach_app.focus_switch_diagnostic \
  --window-id CURRENT_GAME_WINDOW_ID --terminal-pid CURRENT_TERMINAL_PID \
  --duration 60
```

`--terminal-pid` can be omitted if exactly one Terminal.app instance is found.
The selected window must belong to `AI-Aim-Trainer-Test2.app` by default.
IDs are resolved at runtime, not hardcoded into the implementation.

1. Keep Terminal foreground for at least three seconds.
2. Physically click/switch to the standalone Unity game. Keep it foreground
   for at least three seconds; visibility alone is insufficient.
3. Physically switch back to Terminal for at least three seconds.
4. Let the observer finish, or use Control-C after the three phases.

The observer does **not** import the mouse posting module, create/post events,
bind the Unity UDP port, or activate any app. It validates window ownership
separately from foreground identity. It logs each changed before/after pair.

Results:
`~/Library/Logs/AI-Aim-Trainer/focus_diagnostics/assist-<id>.jsonl`

The final `focus_summary` reports:

- `sequence_verified`: the fresh query actually observed Terminal, then the
  chosen game, then Terminal, in that order, without an ownership/query error.
- `stale_value_observed`: at least one raw NSWorkspace value differed from its
  after-pump value. This confirms stale-value behavior in that observed run.
- `transitions`: actual observed PIDs, not an expected sequence filled in by code.
- `input_events_posted=false`, `head_lock_enabled=false`.

An incomplete sequence is not a successful focus test. A complete sequence
with no before/after mismatch demonstrates fresh transitions but does not, by
itself, reproduce the original stale cache symptom. Unit tests use simulated
application objects; they are not real focus-switch verification.

After verification, restart `quartz_matrix.py` normally. Its foreground check
remains mandatory before any manually triggered pulse. This passive observer
does not test or verify synthetic mouse delivery.
