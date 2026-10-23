# Quartz event provenance diagnostic

This is a standalone, explicit diagnostic for the Unity standalone Test3 app.
It uses a read-only event tap scoped to the selected game PID and writes local
JSONL only. No event is posted at launch. One fresh F6 press posts exactly one
small (+/-2) single-axis event; every further pulse needs another F6 press.
F8 or Escape stops the diagnostic immediately. It does not retry, compensate,
change mouse settings, or enable Head Lock.

## Permissions

The process running this command needs:

- **Accessibility** to post its explicitly activated test event.
- **Input Monitoring** so the listen-only event tap can observe mouse movement
  events for the selected game process.

The command checks both permissions and does not prompt for them. Grant them in
System Settings > Privacy & Security to the actual host process: Terminal when
run from this project environment, or Coach.app if launched from its packaged
host. Restart that host after changing permissions. The diagnostic does not
require Screen Recording, and it never suppresses physical mouse/trackpad
events. A local untagged event may be physical input or another untagged source;
the report does not claim to identify it as physical.

## Run

First stop Camera Calibration and Mode 2 workers so nothing else owns UDP port
8767. The standalone game's Quartz diagnostics publisher must be enabled. Keep
Settings/Summary closed and leave the game focused with its cursor locked.
Keep hands off the mouse/trackpad during the short observation.

From the Unity project root, use the current standalone game window ID:

```sh
.venv/bin/python -m coach_app.quartz_provenance --window-id WINDOW_ID --axis horizontal --direction positive
```

The listener arms without moving the camera. Switch focus to Unity, then press
and release F6 once. The command records the tagged event as seen by the
target-process tap and the Unity per-frame history for 0.65 seconds. Each later
trial requires a fresh F6 press. Use `--axis vertical` and/or
`--direction negative` for the other single-axis directions. F8 or Escape exits.

Logs are saved under
`~/Library/Logs/AI-Aim-Trainer/quartz_provenance/`. Each trial includes the
unique event tag, event timestamp, tap callback timestamp, tagged/untagged event
counts, Unity frame sequence and UTC/realtime timestamps, per-frame and summed
Mouse X/Y, camera yaw/pitch, and the unchanged strict Matrix verdict. A tap
event is not proof that Unity consumed it; Unity frame evidence remains separate.

## Reading the result

- One matching tagged event and two Unity input frames indicates the event was
  observed once at the process tap but two frames appeared downstream.
- More than one matching tagged callback indicates repeated observation of the
  same tag at the process tap.
- One tagged event plus untagged movement is mixed-source evidence; the
  untagged event is not automatically attributed to a physical device.
- A missing tag means the tap did not observe the marker. It does not prove the
  event was not delivered to Unity.

The Matrix verdict still rejects two nonzero Unity frames and any excessive,
unexpected-axis, stale, or inconsistent response. This tool reports provenance
evidence; it does not alter or bypass those checks.
