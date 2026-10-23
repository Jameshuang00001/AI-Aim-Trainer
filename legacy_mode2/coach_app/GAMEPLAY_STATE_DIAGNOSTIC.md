# Diagnose Unity gameplay_inactive without input injection

## What is known

Latest reviewed matrix log:
`~/Library/Logs/AI-Aim-Trainer/quartz_matrix/assist-214680adaa6c4c16adf8b8ee264ab38b.jsonl`.
At 2026-10-22 19:50:08.193 America/Toronto, selected/foreground PID both equalled
66661, telemetry age was 29.83 ms, and Unity reported `gameplay=false`.
The old standalone omitted cursor/session/pause flags. Its exact failed Unity
gate **cannot be recovered from that packet**. A visible game and matching
foreground PID do not establish an active, unpaused, cursor-locked session.
This row also coincides with NSWorkspace refreshing from Terminal to Unity.
A packet received 29.83 ms earlier may describe the frame before that switch.
Conversely at 19:50:10.301 the foreground was Terminal while the last fresh
Unity packet still said gameplay=true. These paired observations support a
focus-transition sampling lag, but do not prove which individual gate was false.
The new send timestamps and per-term flags are needed to distinguish that lag
from a persistently open menu, inactive session or unlocked cursor.

The publisher's gate is unchanged:

```text
application focused
AND cursor locked
AND CursorStateManager exists AND GameplayInputEnabled
AND SessionManager exists AND IsSessionActive
AND NOT IsPaused
```

Source behavior: Start Game begins the session and enters gameplay cursor mode.
Settings and Summary enter menu cursor mode: input disabled, cursor unlocked,
session paused. Continue or closing Summary enters gameplay mode again. Session
presence alone does not mean the session has begun. End Session opens the stats
overlay and leaves the session active but paused while that overlay is open.
No changes were made to these behaviors.

## Diagnostic payload v2

`AssistStatePublisher` now sends `precondition_version=2`, while keeping
`diagnostic_version=1` and all existing fields compatible. New details include:

- Focus, cursor lock boolean and mode name, cursor visibility, cursor-manager
  presence and gameplay input permission.
- Session-manager presence, active session, pause, logical summary-open state.
- Settings-manager/UI-manager presence, logical Settings-open state and actual
  Settings/Summary/Start Menu `activeInHierarchy` visibility.
- `sent_at_utc`, Unity frame/realtime, `time_scale` and `gameplay_blockers`.

`gameplay_blockers` is computed from the same snapshot as the original gate:
`application_not_focused`, `cursor_not_locked`, `cursor_manager_missing`,
`gameplay_input_disabled`, `session_manager_missing`, `session_inactive`,
`session_paused`. Every failing term is retained; an empty list means the gate
passed. Panel visibility is separate evidence, not substituted into that gate.
Missing UI managers yield unknown visibility in Python, not an invented closed
panel. The matrix still blocks visible/open menus and every existing precondition.

When opt-in diagnostics are enabled, Unity logs gate changes with UTC timestamp,
frame, blocker list and panel states. No cursor/session/UI setters are called by
the publisher. `UIManager` and `SettingsMenuManager` only gained read-only
visibility properties. Python logging does not alter gameplay.

## Exact Unity 2022.3 standalone rebuild steps

1. Stop matrix/calibration/passive receivers with F8 or Control-C as appropriate.
   Quit the old standalone normally, which also closes its owned Coach. Do not
   leave the old app running alongside the replacement.
2. Open this project in Unity 2022.3. Exit Play Mode. Open
   `Assets/Scenes/SampleScene.unity`. Wait for script import and resolve any
   Console compiler errors before building. These C# changes have not been
   compiled or live-verified by the agent.
3. Select Player's existing **Assist State Publisher**. Keep its Main Camera
   reference assigned (not a weapon camera). Enable **Publish Quartz Diagnostics**.
   Set **Quartz Diagnostic Port = 8767**. The intended normal **Coach State Port
   = 8766**. The reviewed scene currently has *both* ports at 8767, which duplicates
   snapshots on the diagnostic port; this does not itself explain `gameplay=false`.
   The agent has not changed the scene. Set the intended distinct ports explicitly
   before building to preserve the normal Coach worker channel.
4. Optionally assign the actual SettingsMenuManager and UIManager to the new
   read-only diagnostic references. They auto-resolve if omitted; assign them
   explicitly if the scene contains multiple such managers. No need to add
   another publisher or another session/cursor manager.
5. Save the scene. Open **File > Build Settings**. The reviewed
   `EditorBuildSettings.asset` has no scenes listed, so click **Add Open Scenes**
   and ensure SampleScene is checked, at index 0.
6. Select **PC, Mac & Linux Standalone**, **Target Platform: macOS**, and an
   Apple Silicon-compatible architecture (Apple Silicon or Universal as offered).
   Switch Platform if needed. A Development Build is optional; no special input
   or camera settings are required.
7. Click **Build** and replace
   `/Users/james/Desktop/AI-Aim-Trainer-Test2.app`. Confirm the replacement. Launch
   that rebuilt app, not a copy from another folder. No Coach.app rebuild is
   required. Its existing auto-launch/IPC can remain enabled.
8. Re-detect the new game window ID. Rebuilding/relaunching changes PIDs and
   window IDs; never assume the historical 66661 / 76076 still apply.

## Passive state recording (no synthetic events)

From `/Users/james/UnityProjects/AI-Aim-Trainer`, replace CURRENT_WINDOW_ID:

```sh
.venv/bin/python -m coach_app.gameplay_state_diagnostic \
  --window-id CURRENT_WINDOW_ID --duration 120
```

This listens exclusively on localhost UDP 8767. Stop other receivers first;
the recorder never steals/reuses a bound port. It reads foreground state using
the verified Cocoa-run-loop query and has no posting/movement method. It never
activates apps, presses keys, changes gameplay, or calls Nebius.

Perform these actions **physically** while the observer runs:

1. Focus the game on its Start Menu. Expect `session_active=false`, Start Menu
   visible and blockers including `session_inactive` / `cursor_not_locked`.
2. Click **Start Game**, keep the game focused. Expect active session, locked
   cursor, enabled gameplay input, `paused=false`, no visible panels, and
   `gameplay=true` with `gameplay_blockers=[]`.
3. Press **Escape** to open Settings. Expect Settings visible, cursor unlocked,
   input disabled, paused, and those exact blockers in the packet.
4. Click **Continue** (or close Settings with Escape). Expect the state from
   step 2 again after input/cursor state has updated.
5. Open Settings, click **End Session**. Expect Summary logically open/visible,
   Settings hidden, session still active but paused/unlocked/input disabled.
6. Press **Escape** to close Summary. Expect gameplay restored without resetting
   stats or returning to Start Menu.
7. Switch to Terminal and back to the game. Background focus loss can add
   `application_not_focused`; use timestamps rather than assuming each printed
   row represents the app currently being viewed. Control-C stops the observer.

If `precondition_version` is missing/old, the wrong or old build is still running.
Do not guess individual flags from its combined gameplay value. If a menu is
visible while gate flags claim normal gameplay, the packet shows both facts;
keep input tests blocked and investigate that inconsistency.

## Precise records to inspect

Python JSONL:
`~/Library/Logs/AI-Aim-Trainer/gameplay_diagnostics/assist-<id>.jsonl`

Unity log:
`~/Library/Logs/DefaultCompany/AI-Aim-Trainer/Player.log`

Each Python record includes Unity send time/frame, reception age, current
foreground PID, individual state flags, publisher-provided blocker list, and
the diagnostic's rejection list. Example when Settings is open:

```text
foreground PID == selected PID
session_active=true, paused=true, cursor_locked=false
settings_panel_visible=true, gameplay_input_enabled=false
gameplay_blockers=[cursor_not_locked, gameplay_input_disabled, session_paused]
```

That example is an expected state, not a claimed live observation. A real v2
record is required to identify the current standalone's precise blocker.
Head Lock stays disabled; no synthetic pulses are needed for any step above.
