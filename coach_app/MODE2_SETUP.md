# Phase 2: Controlled YOLO Head Lock (our Test3 game only)

Default OFF; Start defaults to **Dry run**, with no mouse posting. The active UI
uses `controlled_assist.py`; the older `aimbot.py` investigation controller stays
interlocked and is not the UI's correction path. Its conservative HeadTracker is
reused. No environment variable enables live correction. No firing, cursor warp,
camera-sensitivity change, Unity code change, training or external-game support.

## Preconditions

- Run `AI-Aim-Trainer-Test3.app`. Both normal state **8766** and chunked diagnostic
  state **8767** must be enabled. Stop calibration/matrix/preview/other receiver
  processes before Start Assist. Ports are bound exclusively, never shared/stolen.
- Use the exact rebuilt `dist/Coach.app`. Verify Screen Recording and actual
  `AXIsProcessTrusted` authorization for this app; an ad-hoc rebuild can require
  reauthorization. Never reset/bypass TCC or rely on a Terminal process's grant.
- A complete, RELIABLE 15-trial matrix calibration with its paired JSONL is
  required. The loader selects the newest successful report, not a newer failed
  attempt. Gains are recomputed from controlled trials. Its PID, window ID,
  executable, sensitivity, FOV and aspect must match the current game. Restarting
  the game requires recalibration; there is no hardcoded 0.05 fallback.
- The current model must identify class 0 as `xbot_head`. Only >=0.50 confidence
  boxes wholly inside the captured gameplay region qualify. Three fresh spatially
  consistent detections are required. Target identity is retained; ambiguity,
  occlusion or sudden identity jumps stop the burst rather than choosing a new bot.

## Capture alignment

The capture is window-specific and excludes Coach, not an arbitrary desktop area.
Full-window capture works ONLY when the image contains actual game content with
the real crosshair at image center. Title bars, letterboxing and decorative
framing can invalidate this. The image aspect must match camera telemetry within
1%; mismatch fails closed. Matching aspect alone does not prove center alignment:
visually confirm the crosshair against a saved preview before live use.

If necessary, save a separate explicitly selected gameplay-content crop:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id CURRENT_WINDOW_ID --select-region --config yolo_dev/capture_region.assist.json --preview-only
```

Or use its existing `--crop X Y WIDTH HEIGHT --save-crop` options instead of
dragging. Coordinates are captured-image pixels; exclude the title bar and make
the crosshair exactly central. Do not copy unverified example coordinates.
Coach looks for `yolo_dev/capture_region.assist.json` under COACH_APP_ROOT, then
`~/Library/Application Support/AI-Aim-Trainer/capture_region.assist.json`.
Use the latter for a packaged install with no project-root reference. The file
must belong to the selected app/window size. A changed crop, capture dimensions
or deadzone invalidates the live dry-run proof; repeat dry-run. Editor and normal
preview crop configuration are unchanged. No crop is inferred from aspect alone.

## Offline checks first

```sh
.venv/bin/python -m unittest coach_app.test_controlled_assist coach_app.test_camera_calibration coach_app.test_quartz_matrix coach_app.test_diagnostic_udp
.venv/bin/python -m coach_app.replay_head_lock PATH_TO_RECORDED_GAME_IMAGE.png
```

The replay tool runs existing YOLO on CPU over saved images only. It reports
confidence, dx/dy and proposed delta or exact projection rejection. It opens no
sockets, captures no screen and sends no input. It CANNOT create live permission.
In development, two old validation images yielded 2/3 heads but correctly failed
the projection gate: their 2332x1250 aspect differs from the calibrated Test3
camera. They were not stretched/cropped merely to force a passing result.
Recorded reliable Unity calibration replays at approximately 0.05 deg/delta.
Mocked loop tests cover delivery loss, wrong axes/gain, multiple input frames,
target/telemetry/focus loss, menus/pause, RMB release, emergency and rate limits.

## Exact dry-run steps

1. Quit old Coach and diagnostic receivers; launch the rebuilt Coach through
   Unity or `open dist/Coach.app`. Do not run two Coach instances.
2. Start Test3 gameplay, close Settings/Summary and keep the cursor locked.
   Recalibrate Camera if this is a new game PID/window or camera configuration.
3. Select Mode 2 and the exact standalone window using Detect or its manual ID.
   Keep **Dry run checked**, deadzone **8**. Check Calibration only reads the
   saved report; it sends no verification pulse.
4. Click **Start Assist**. Return focus to Unity and hold physical RMB, keeping
   the mouse still. The initial UI-to-game focus transition waits without input.
5. Keep the crosshair outside the 8-pixel deadzone near one static head. Observe
   confidence, dx/dy, gains, proposed events and **Sent (0, 0) (0/5)** with
   **Observed no input (dry run)**.
   After three bounded proposals the worker stops with
   `dry_run_passed_no_input_sent`. This proof is in memory only and is bound to
   calibration/model digests, PID/window, crop, dimensions and deadzone.
6. If any safety check fails, read the exact reason, fix it and repeat dry-run.
   No checkbox/Start combination can skip the proof requirement.

## Exact first live test

1. Begin with one static bot, a clear view and crosshair near (not on) its head.
   Keep the game comfortably away from camera pitch limits. Do not move the
   physical mouse during response observation: contamination rejects the trial.
2. After dry-run passes and workers stop, uncheck **Dry run**. Read and explicitly
   approve the separate live-correction dialog. This does NOT start correction.
3. Click **Start Assist**, return focus to the game, then hold RMB. Three stable
   detections and the shared READY/quiet-baseline gates must pass first.
4. Expect very slow, single-axis increments: **+/-2 counts**, around **0.1 degree**
   with 0.05 calibration. Max budget 8 counts/second, ramp 16 counts/second^2;
   matrix observation/cooldown makes the actual pace considerably slower.
   Only one event may be pending. It must pass the unchanged 300 ms quiet pre,
   >=400 ms pulse and >=400 ms quiet post windows, single-input-frame/direction/
   cross-axis/rotation checks and +/-20% calibrated-gain check. A new capture
   AFTER feedback completion is mandatory before another correction.
   Both first-fragment arrival and Unity's UTC send timestamp must be under
   200 ms old, so queued old packets cannot masquerade as fresh observations.
5. Correction stops inside the configured 4-32 pixel deadzone (default 8), when
   another quantized pulse could overshoot, after **five corrections**, or after
   **ten seconds** of target holding. No automatic rearming/retry exists.
6. Release RMB at any time: no new post is allowed. If feedback was pending,
   that burst ends unverified rather than assuming delivery. A posted OS event
   cannot be recalled. **F8/ESC or Stop** always latches OFF. Focus loss, menus,
   pause, unlocked cursor, stale data, changed PID/camera/crop, target loss or
   inconsistent response also end the burst. Native gates recheck RMB and Stop
   under the same posting lock, immediately before the existing PID backend.
7. Inspect logs after each burst. Start defaults back to dry-run; a subsequent
   live burst requires another explicit confirmation. Do not increase speed or
   relax thresholds to make silent/inconsistent delivery pass.
8. Only after static tests are satisfactory, manually repeat with moving targets,
   multiple heads and occlusion. Verify no target jumping, no correction after
   RMB release/focus loss/F8, and no shots fired except physical user fire input.

## Feedback and logs

Coach shows confidence, dx/dy, calibration, READY/ACTIVE/OFF, sent correction
count/delta, actual observed yaw/pitch (or pending), and stop reason. A sent event
is never presented as a verified camera response. Completion details use the existing report area.
JSONL lives at `~/Library/Logs/AI-Aim-Trainer/assist/assist-<id>.jsonl`.
Events include start bindings/limits, detection, proposal, posted/native event,
individual Unity input frames, full observed-camera-response matrix verdict,
post-correction detection, acquisition and safety interruptions. Dry-run proposals
are NOT marked as actual corrections or verified camera responses. No screenshots,
API keys or network analysis requests are written by this controller.

Live correction has NOT been exercised by the agent. Mock tests and replay do
not establish real closed-loop stability, moving-target behavior or hardware
provenance. Manual opt-in testing above remains necessary. Mode 1/Nebius and the
existing UI/IPC/Keychain paths are unchanged. Unity needs no rebuild. Coach.app
must be rebuilt for its new Python controller/UI; see MACOS_APP.md.
