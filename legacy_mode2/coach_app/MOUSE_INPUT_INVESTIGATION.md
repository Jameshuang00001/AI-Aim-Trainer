# macOS / Unity mouse input investigation

## Established from this project

- `ProjectSettings.asset`: `activeInputHandler: 0` (legacy Input Manager).
- No `com.unity.inputsystem` dependency in `Packages/manifest.json`.
- `InputManager.asset`: Mouse X/Y are mouse-movement axes 0/1, dead/gravity 0,
  sensitivity **0.1**, unchanged by this investigation.
- PlayerController consumes `Input.GetAxis("Mouse X/Y")`, multiplies by existing
  player sensitivity, then rotates yaw/pitch. No OS cursor position is used.
- Coach creates a Quartz `kCGEventMouseMoved` at the current absolute cursor
  location, sets `kCGMouseEventDeltaX/Y`, and calls `CGEventPostToPid(UnityPID,event)`.
  That is a process-targeted Quartz event, not insertion of a hardware HID report.
  `CGEventPostToPid` returns void: backend `move() == True` means it was submitted,
  **not** accepted by Unity or consumed by its legacy relative-input path.
  It is still a MouseMoved event while RMB is held, not a RightMouseDragged event;
  passing the right-button argument does not change the chosen event type. This
  is another delivery/translation difference to investigate, not a verified cause.

Reported A/B result: physical movement rotates the camera, an isolated posted
pulse produces yaw=0/pitch=0, and earlier nonzero responses were physical motion.
This rules out treating those earlier responses as successful synthetic input.
Permission authorizes posting; it does not establish compatibility with Unity's
locked-cursor input path. The likely boundary is between process-posted Quartz
events and Unity's macOS legacy relative input. Whether Unity's native backend
filters synthesized events, polls another device stream, or loses the fields in
translation is **not established** by project C# or the public AX result. Do not
claim a proven raw-HID implementation without native engine-level evidence.

## Safety interlock

### Read-only destination audit

Run from a host already authorized to inspect game window metadata:

```sh
.venv/bin/python -m coach_app.audit_destination
# If multiple windows exist, use a CURRENT window ID:
.venv/bin/python -m coach_app.audit_destination --window-id CURRENT_WINDOW_ID --expect-app AI-Aim-Trainer-Test.app
```

This dynamically resolves `kCGWindowOwnerPID` and `proc_pidpath`, verifies the
expected .app bundle, and prints the separate window ID, destination PID and
executable. It posts no events and does not need mouse/AX interaction. A missing
window record under restricted Screen Recording metadata is not proof of a dead
game or of an incorrect injection PID.

The source backend now logs this same identity at startup and revalidates window
owner PID/executable immediately before each diagnostic post. Owner changes cause
a fail-closed error. The current running packaged app is not hot-patched; rebuild
and restart it to load new backend logging. No temporary PID is saved in source.

`HEAD_LOCK_INPUT_PATH_VERIFIED = False` explicitly blocks all head corrections,
even if the user physically moves the camera during Verify. It is not configurable
through the UI or environment. YOLO can still run. Verify is diagnostic-only: the
same single bounded (2,2) pulse, only while held/focused/safe, and logs
`verification_pulse_posted` and `diagnostic_camera_response` in normal assist JSONL.
Zero response keeps detection running; no tuning, alternative injection, cursor
warp, HID emulation or automatic firing is introduced. Existing response thresholds
are unchanged and cannot unlock the investigation interlock. F8/ESC/Stop remain.

## Collect comparable Unity input traces

In Editor/Development builds, MouseInputDiagnostics attaches read-only to the first
Player automatically; otherwise attach it manually. Recording defaults OFF.

1. Stop/relaunch the updated Coach (the packaged app must be rebuilt). Start an
   active Unity session, keep focus in Game view and the cursor locked.
2. Press **F9** to record ten seconds. Default phase is `physical_baseline`. Move
   the real mouse deliberately. Check Console for nonzero `axis_x/y`, consumed
   values, `look_processed:true`, and camera deltas. F9 can stop early.
3. In Coach Start detection and request Verify. Return to focused Unity. Before
   holding RMB, press **F10** to choose `synthetic_attempt`, then F9 to record.
   Keep the real mouse completely still; hold RMB to send the single existing
   diagnostic pulse. Correlate UTC timestamps with the Coach JSONL pulse record.
   Do not count motion from clicking/returning to Unity as a synthetic response.
4. F9 stops, otherwise recording ends automatically. It logs every frame for ten
   seconds, including zero frames; Console output is throttled to four lines/sec.
   Files: `Application.persistentDataPath/mouse_input_diagnostics/*.jsonl`; Unity
   prints each exact path. The diagnostic does not change camera, cursor or input.
   Use Fn-F9/Fn-F10 if macOS maps those function keys to system actions.
5. Compare one or both captured files:

```sh
.venv/bin/python -m coach_app.compare_mouse_input /absolute/physical.jsonl /absolute/synthetic.jsonl
```

The report excludes unfocused/menu/paused/unlocked frames and compares nonzero
legacy axes, raw legacy axes, consumed input and actual angular response. Raw
legacy axes are still Unity input units, **not raw hardware counts**. F10 labels
are manual phase labels, not event-source attribution. If physical axes are nonzero
but synthetic-phase axes remain zero while look processing is enabled, the failure
is before PlayerController's rotation math. If look processing is disabled, fix
focus/session gates before drawing that conclusion. If both phases show input,
exclude physical contamination before claiming injection works.

No live A/B samples were fabricated by automated tests. Interactive physical input
must be collected by the tester. Remove/disable this diagnostic after investigation.

## Next decision

For an isolated, per-keypress comparison of PID posting versus HID-tap posting,
see [QUARTZ_DELIVERY_TEST.md](QUARTZ_DELIVERY_TEST.md). It uses a separate opt-in
Unity diagnostic telemetry port and cannot enable Head Lock.

Do not migrate input systems, increase sensitivity, lower verification bounds or
warp the cursor to make this backend appear successful. If this Quartz path remains
incompatible, keep it unsupported. Any future explicit in-game assist interface
would be a separate, opt-in design for this owned Unity game, not evidence that OS
synthetic relative input was verified.
