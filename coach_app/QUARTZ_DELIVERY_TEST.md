# Isolated Quartz delivery comparison

**Controlled-repeat update:** see [QUARTZ_FINDINGS.md](QUARTZ_FINDINGS.md) for the
eight recorded trial findings and the new F4 stationary-control / reverse-direction
protocol. The updated runner records pre/pulse/post traces, and completes each
test after at least 0.4 seconds of pulse observation plus 0.4 seconds of post
observation. Wait for its result before the next activation. F5 remains the
deliberate physical baseline, not the zero-input control.

This test does not start YOLO, aim at targets, fire, change cursor state, or modify
Head Lock's hard-disabled interlock. It runs separately from the normal Coach UI.
No mouse events are generated at launch. Each fresh F6/F7 press requests only one
mouse-moved event with `(dx,dy)=(2,2)` by default, or `(-2,-2)` in the explicit
negative-direction run (same magnitude ~2.83 counts). There is no configurable
large delta, repetition loop, or automatic sequence. Both methods construct exactly
the same event at the existing cursor location; only dispatch changes:

- **A / F6:** `CGEventPostToPid(currentGameOwnerPID,event)` targets the verified PID.
- **B / F7:** `CGEventPost(kCGHIDEventTap,event)` enters the global event stream.
  The PID is focus/ownership context, NOT an argument to this API. HID-tap posting
  is not a hardware HID report and does not prove Unity compatibility.

No `CGWarpMouseCursorPosition`, absolute-position displacement, mouse clicks, drag
substitution, event-source impersonation, or private APIs are used. macOS may still
interpret a posted event as pointer input; do not test over other applications.

## Exact manual steps

1. In Unity select Player's **AssistStatePublisher**. Assign the real gameplay camera.
   Enable **Publish Quartz Diagnostics**, leave **Quartz Diagnostic Port = 8767**.
   Build/run the updated standalone game. Old binaries without these fields cannot
   supply required telemetry and the runner will reject tests without sending input.
   This component observes input; it never injects it or changes camera sensitivity.
2. In Coach click **Stop Assist** and do not request its separate Verify action.
   Keep normal Coach running if desired. Existing UI/HTTP IPC/telemetry ports are
   unchanged; this test uses a separate localhost UDP receiver on 8767.
3. From the project root, in your authorized Terminal, identify the current game
   window (PIDs/window IDs are never fixed):

```sh
.venv/bin/python -m coach_app.audit_destination
```

   Use `--window-id CURRENT_WINDOW_ID` if multiple windows exist. The audit checks
   the expected `AI-Aim-Trainer-Test.app` bundle, owner PID and executable.
4. Start the isolated runner, substituting its current window ID:

```sh
.venv/bin/python -m coach_app.quartz_delivery_test --window-id CURRENT_WINDOW_ID
```

   For a differently named owned build, supply `--expect-app YourBuild.app`.
   The runner checks **its own** Accessibility authorization. If denied, stop and
   grant the launching host/Python access manually, then restart. Coach.app's grant
   does not automatically authorize this Terminal-launched Python. Metadata lookup
   may also require existing Screen Recording permission; no screenshot is taken.
   No permissions are requested or bypassed. The packaged Coach is not rebuilt or
   modified by this isolated tool.
5. Focus the standalone Game window, start/continue an active session with the
   cursor locked, and wait at least one second. Leave the mouse buttons released.
   The test does not focus the game or lock its cursor on your behalf.
6. Optional physical baseline: press **F5** and gently move the physical mouse
   during the next **0.4 seconds**. No event is posted for F5. This verifies the
   received axes and camera telemetry for physical input.
7. Stop physical mouse movement for at least 0.3 seconds. Press/release **F6** once.
   Do not move the mouse for the next 0.4 seconds. Exactly one PID-addressed pulse
   is attempted. Inspect the terminal result after the observation window.
8. Wait at least one second, keep the mouse still, then press/release **F7** once.
   The same single pulse is attempted through the HID event tap. Do not switch
   applications during either test. Repeat only by another deliberate key press.
   Keys held at launch or during a pending test do not queue or repeat tests.
9. **F8 or Escape** immediately stops the runner; Ctrl-C also stops it. Use Fn with
   function keys if macOS assigns them system actions. An already posted event
   cannot be recalled, but no further pulse is generated. Focus loss, stale Unity
   telemetry (>200 ms), permission loss or changed ownership prevents further posts.
10. Disable **Publish Quartz Diagnostics** after finishing. Head Lock remains OFF
    even if either method shows a response; do not change its interlock based on
    a single trial or contaminated camera movement.

The input-state APIs must be able to observe your function keys. If no activation
is seen, check Fn/system shortcuts and the host's macOS permissions rather than
automating key presses or weakening safety checks. Ensure the F8 route works before
performing a pulse. The runner also recognizes Unity's own F8/Escape heartbeat flag.

## Logs and interpretation

The exact log path is printed at launch. JSONL files are under:

```text
~/Library/Logs/AI-Aim-Trainer/quartz_diagnostics/assist-<unique-id>.jsonl
```

Each activated test records a test ID, UTC timestamps, dispatch method, game window
ID, dynamically verified owner PID/executable, requested/posted dx/dy, Unity Mouse
X/Y sums and raw-axis sums, count of frames receiving input, actual yaw/pitch change,
and success/failure. Aborts or unavailable telemetry have null observation fields
rather than fabricated zeros. Results link to the posted event by test ID. Missing
focus/quiet-baseline/telemetry is logged as a rejection with **no event posted**.

Unity accumulates input **every frame** before sending snapshots at ~25 Hz, so an
individual delta is not lost between packets. These are Input Manager units, not
hardware counts or pixels. Existing mouse sensitivity and camera bounds are not
changed. Synthetic response assessment uses the original strict bounds
`0.005 < yaw < 3` and `0.005 < pitch < 3`, plus actual nonzero Unity input frames.

- `no_unity_delta`: no delta reached the legacy axes during the observation.
- `input_received_no_camera_rotation`: axes changed but the camera did not.
- `response_outside_existing_bounds`: some input/rotation occurred, but it did not
  meet the original verification conditions; raw values are retained for analysis.
- `observed_response`: telemetry meets those conditions, **not proof of source**.

Physical movement after the pulse can still contaminate a result. Every result
therefore keeps `independently_verified: false` and `head_lock_enabled: false`.
Compare repeated A/B trials against stationary/no-event and physical baselines.
Neither post API provides an acknowledgment that Unity consumed the event.

## Automated checks

```sh
.venv/bin/python -m unittest coach_app.test_quartz_delivery -v
```

Tests replace all Quartz input calls, focus state, clocks and telemetry. They cover
no-event startup, held-key suppression, one pulse per activation, stale/focus/AX
rejection, emergency stop, unchanged bounds and PID-vs-global dispatch. No live
mouse tests were run automatically; the A/B conclusion awaits your manual trials.
