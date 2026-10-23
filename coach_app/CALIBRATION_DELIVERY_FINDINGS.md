# Calibration zero-input investigation (2026-10-22)

## Evidence, not an assumed fix

The precise cause of the later silent delivery failure is **not established**
by the old logs. They contain no native post-return record, event timestamp,
event readback or foreground PID captured immediately around dispatch. A
successful API invocation is also not an acknowledgement from Unity.

The known difference is intermittent runtime delivery, not a demonstrated
single-axis construction bug or demonstrated UI focus loss:

- `assist-027a885eebe347eba6c871358ccffa24.jsonl` (18:35 local) contains seven
  valid calibration trials: two zero controls and five pulses. Horizontal
  +/-2 gave approximately +/-0.05 Mouse X and +/-0.1-degree yaw; vertical +/-2
  gave approximately -/+0.05 Mouse Y and +/-0.1-degree pitch. It ultimately
  aborted for `physical_input_in_baseline`, not failed pulse delivery.
- The next three logs, `assist-3d5ce07927734d71a2eb4d878318f1a8.jsonl`,
  `assist-19d0cb1b3c174b80a5fed2c057436c20.jsonl`, and
  `assist-6b8fa1ba70bb4b6d831f8f439affdf21.jsonl` (18:43-18:44), each pass a
  zero control and then measure zero input/rotation for a +2/0 pulse.
- All four runs identify window 76076 and PID 66661, whose executable was
  `/Users/james/Desktop/AI-Aim-Trainer-Test2.app/Contents/MacOS/AI-Aim-Trainer`.
  These are historical IDs, never configuration defaults.
- Every saved sample reports `gameplay=true`. In the unchanged Unity publisher,
  this requires application focus, locked cursor, enabled gameplay input,
  active session and no pause. The failed pulse trials advance 51-56 Unity
  frames over approximately 868-909 ms. Their 438-451 ms pulse windows and
  417-471 ms post windows contain no late response. This is not a frozen
  telemetry stream or a shortened observation window.

All logs above are under
`~/Library/Logs/AI-Aim-Trainer/camera_calibration/`.

## Line-by-line path comparison before refactoring

| Concern | Isolated A/B | Coach calibration |
| --- | --- | --- |
| Event source | `CGEventCreateMouseEvent(None, ...)` | Same |
| Position | Current `CGEventGetLocation(CGEventCreate(None))` | Same; neither warps |
| Event type/button | `kCGEventMouseMoved` / `kCGMouseButtonRight` | Same; no click events |
| Fields | `kCGMouseEventDeltaX/Y` = +/-2, +/-2 | Same fields; +/-2,0 or 0,+/-2 |
| Delivery | `CGEventPostToPid(owner_pid, event)` for F6 | Same |
| Authorization | `accessibility_trusted()` through a wrapper | Direct same AX function |
| Destination | Window owner PID + executable pinned; app name CLI configurable | Same resolver; Test2 app explicitly required |
| Focus gate | NSWorkspace foreground PID + fresh Unity gameplay state | Same, plus extra per-tick destination/AX checks |
| Cursor/menu gate | Unity composite `gameplay` telemetry | Same |
| Activation | Fresh F6 key edge, no events on launch | Same; Coach button only arms |
| Windows | >=300 ms quiet pre, >=400 ms pulse, >=400 ms post | Same |
| Runtime host | Terminal/Python, diagnostic loop | Packaged Tk app, background worker |

Clicking Coach initially takes focus, but calibration waits for focused gameplay
and aborts on subsequent observed loss. The UI does not intentionally refocus
Coach during a trial. There is no saved evidence of UI-induced focus loss in
the failed trials. Process identity, native event delivery, transient changes
between telemetry samples, and physical input provenance remain variables to
measure, not established explanations. Do not change sensitivity to mask this.

## Changes

Both paths now call **one** `post_relative_pulse()` helper. It preserves their
original event construction and dispatch, accepts only fixed bounded deltas,
and records event timestamp, type, current location, delta field readbacks,
destination PID, and monotonic post start/end times. No new event source or
cursor warp is introduced.

Calibration adds `calibration_startup`, `post_attempt`, `native_post_begin`,
`native_post_returned`, and `post_returned` records, or explicit blocked/error
records. These include the dynamic window/owner/executable, foreground PID,
actual AX trust result, Coach PID/thread, pre/post focus state, and latest Unity
gameplay flag/telemetry age. Existing samples/results record Unity axes/raw
input and yaw/pitch before/after. The API returning sets `post_call_returned`,
**not** `unity_acceptance_confirmed`. Zero controls never post events.

## Next explicit manual comparison

1. Restart the rebuilt Coach. Use active Test2 gameplay, close Settings/Summary,
   then select its current window in Coach. Click Calibrate Camera, return focus
   to the game and leave the mouse physically still for one second.
2. Press/release F6 for the zero control; wait two seconds. Press/release F6 once
   for the horizontal trial. No further pulse runs without another fresh key.
   F8/Stop always cancels. If it fails, preserve both JSONL and report files.
3. Stop calibration to release port 8767. From the project root, start the
   separate comparison explicitly, substituting the current window ID:

   ```sh
   .venv/bin/python -m coach_app.quartz_delivery_test --window-id WINDOW_ID --expect-app AI-Aim-Trainer-Test2.app
   ```

4. Return focus to Unity and keep the physical mouse still. Press/release F4
   (zero), wait two seconds, then F6 (one +2/+2 PID pulse). Stop with F8.
   Reverse trials require restarting the diagnostic with `--direction negative`.
5. Compare native `event_dx/dy`, event timestamp, destination and foreground
   PIDs, post-call return, and the first changed Unity samples. A/B logs are in
   `~/Library/Logs/AI-Aim-Trainer/quartz_diagnostics/`. A return with zero Unity
   response remains a failed trial, not successful delivery verification.

Calibration cannot be called fixed or reliable until new real Unity telemetry
confirms receipt. Head Lock remains disabled; thresholds and gameplay are
unchanged. Automated tests mock all native posting and send no real input.
