# Phase 1: isolated camera calibration

This diagnostic estimates **degrees of camera rotation per requested Quartz
delta**, using measured Unity telemetry. It does not establish hardware-event
provenance, change sensitivity, fire, track heads, or unlock continuous Head Lock.
The existing detector and Mode 1 analysis remain separate.

## Standalone test steps

1. Use `AI-Aim-Trainer-Test3.app`. Its existing `AssistStatePublisher` must have
   **Publish Quartz Diagnostics** enabled, publishing to localhost UDP **8767**.
   Keep normal Coach state on **8766**. The existing chunked frame-history
   publisher is required. The current working Unity build needs no change or
   rebuild. Stop matrix/A-B/read-only receivers so they release port 8767.
2. Quit the old Coach before rebuilding. From the project root:

   ```sh
   .venv/bin/python -m PyInstaller --noconfirm --distpath dist --workpath build/coach coach_app/Coach.spec
   codesign --verify --deep --strict dist/Coach.app
   ```

   Start the standalone game normally so its existing bridge launches Coach.
   If macOS requests authorization after the ad-hoc rebuild, manually authorize
   the rebuilt `dist/Coach.app` in Accessibility. Nothing bypasses this check.
   The packaged smoke test during this integration returned AX authorization
   **false** for the rebuilt app. Before live trials, enable the exact rebuilt
   Coach.app in System Settings > Privacy & Security > Accessibility, fully quit
   and relaunch it, and confirm authorization using `--diagnose-accessibility`.
   UI/model smoke success is not permission or camera-calibration verification.
3. Start a training session. Close Settings/Summary so gameplay is active and
   the cursor locked. Choose a position away from pitch limits. Do not change
   sensitivity, FOV or aspect during the test.
4. Expand Coach, choose Mode 2, detect/select the standalone window (manual ID
   also works), and click **Calibrate Camera**. Do not click Start Assist.
   If a detector is still stopping, wait and click Calibrate Camera again.
   This only arms the diagnostic: **no event is posted by the button**.
5. Return focus to the game, release all keys and keep the physical mouse still.
   Wait for READY (350 ms and three fresh distinct Unity frames), then for a
   quiet baseline. Press and release **F6** once per trial, waiting
   at least two seconds between presses. On keyboards using media keys, use Fn-F6.
   A held key never repeats a trial. A press without a sufficient quiet baseline
   is consumed without sending an event; wait and press again.
6. Complete this five-trial sequence **three times** (15 presses total):

   | Trial in each group | Requested dx/dy | Expected response |
   | --- | --- | --- |
   | 1 | 0 / 0, no event | No mouse input or rotation |
   | 2 | +2 / 0 | Right yaw only |
   | 3 | -2 / 0 | Left yaw only |
   | 4 | 0 / +2 | Down pitch only |
   | 5 | 0 / -2 | Up pitch only |

7. **F8 or Escape cancels immediately**; Coach's **Stop** button also cancels.
   Switching Coach modes or shutting down Coach stops calibration. Clicking
   Coach or opening Settings/Summary cancels the current observation and returns
   to **WAITING_FOR_GAME**, preserving previously validated trials. Return to
   gameplay, wait for READY, release F6, then press again. No pulse is queued
   while waiting, and interrupted trials are not counted as valid.

No timer triggers another pulse. The only backend is `CGEventPostToPid`, with
the selected window's dynamically resolved PID and executable rechecked before
posting. Only `AI-Aim-Trainer-Test3.app` is accepted by this diagnostic.

## Measurements and safety

Every trial records a quiet pre-window (at least 300 ms), a pulse observation
window (at least 400 ms), and a quiet post-window (at least 400 ms). These are
telemetry reception windows, not precise hardware-input latency measurements.
Calibration now subclasses the Quartz Matrix engine, reusing `evaluate`,
precondition_snapshot, the stable READY/waiting state, isolated posting and
pre/pulse/post observation logic. It no longer has a separate movement validator.
The JSONL includes requested deltas, timestamped individual input frames, raw
and consumed Mouse X/Y, camera yaw/pitch, complete history checks and pre/post
results. Chunk reassembly is shared with the matrix and publishes only complete,
checksum-verified snapshots; freshness starts at the first received fragment.
An in-flight next batch does not invalidate or refresh the prior complete state.
Calibration additionally requires published individual cursor/session/menu flags;
missing values are rejected, not inferred from `gameplay=true`.

Missing/stale telemetry (>=200 ms), lost focus, menus, pause or unlocked gameplay
return to WAITING_FOR_GAME without dispatching delayed input. Foreground state
comes from the corrected Cocoa query serviced on Tk's main thread every 100 ms;
a stale foreground observation blocks dispatch too. Calibration aborts on
permission loss, changed window/PID/executable or camera settings, invalid
counters, >=3-degree rotation on either axis, unexpected
direction/cross-axis response, multiple nonzero input frames, or a >20% change
from the same axis's previously measured mean gain. Controls must remain quiet.
The original 0.005-degree response floor is not lowered.

A reliable report requires the whole 15-trial plan to pass, including all three
controls, three trials of each sign on each axis, and <=20% coefficient of
variation per axis. It includes mean gain, standard deviation, relative
variation and maximum rotation prediction error. Partial/aborted reports are
never reliable. Physical input exactly during a pulse cannot be ruled out by
Unity's frame-level telemetry alone. This integration has been checked against
the recorded matrix log `assist-5185f0395dd04cd8a29def127cc53a76.jsonl`: its four
valid horizontal responses retain their matrix verdict and approximately
0.05 degrees/delta factor. Those recordings do NOT verify all four directions
or a complete calibration; the manual plan above remains required.

## Output

`~/Library/Logs/AI-Aim-Trainer/camera_calibration/assist-<id>.jsonl`

`~/Library/Logs/AI-Aim-Trainer/camera_calibration/assist-<id>.report.json`

Coach displays current direction, valid/required trials, horizontal/vertical
factors (degrees per requested Quartz delta), reliability and precise failure
reason. The finished scroll-area summary is readable; full per-frame JSON stays
in the report files. Abort records are also saved; failures before telemetry/log setup show a
clear status/Console message. No data is sent to Nebius by this diagnostic.

Automated tests use mocked backends and synthetic telemetry only:

```sh
.venv/bin/python -m unittest coach_app.test_camera_calibration
```

Passing these tests is **not real camera calibration verification**. A real
standalone run with measured camera telemetry is still required. Even a reliable
gain estimate does not enable Head Lock or set input-path verification flags.
