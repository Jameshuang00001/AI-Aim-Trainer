# Packaged macOS Coach

## Build

From `/Users/james/UnityProjects/AI-Aim-Trainer` on Apple Silicon:

```sh
.venv/bin/python -m pip install -r coach_app/requirements-build.txt
.venv/bin/python -m PyInstaller --noconfirm --distpath dist --workpath build/coach coach_app/Coach.spec
codesign --verify --deep --strict dist/Coach.app
```

Output: `/Users/james/UnityProjects/AI-Aim-Trainer/dist/Coach.app`
Bundle ID: `com.ai-aim-trainer.coach`. This is an arm64 windowed, onedir bundle,
not a script wrapper or a one-file temporary extraction. It includes Python,
Tk/Objective-C dependencies, OpenAI/Keychain client, Torch/MPS, torchvision native
libraries, Ultralytics and the current `best.pt`. No API keys, `.env`, screenshots,
labels, session logs or Keychain items are copied. Existing `.venv` stays usable.

The local build is ad-hoc signed, **not notarized**. The bundle ID is stable, but
ad-hoc signatures can change with rebuilds and may require reauthorization.
For stable update identity/distribution, build using your own existing Apple
signing identity: set `COACH_CODESIGN_IDENTITY` before the build. This project does
not create certificates, change trust, disable Gatekeeper or reset TCC.

Build-environment note: the first Ultralytics module scan added its optional
`lap==0.5.13` dependency. Existing Coach/ML dependencies were not upgraded, and
`pip check` passes. The spec disables further Ultralytics auto-installation.

## Unity launch / ownership

CoachAppBridge first connects to an existing Coach as before. If none is running,
on macOS it prefers `dist/Coach.app`, then `/Applications/Coach.app`, or its
explicit Packaged Coach Path Inspector field. It launches using
`/usr/bin/open -n -g -W` (Launch Services), not the app's internal executable.
If no package exists, it uses `.venv/bin/python coach_app/main.py` as before.
An application that exists but fails startup is diagnosed, not silently replaced
with Python under a different permission identity.

The project root, local IPC port/token and a launch nonce are passed explicitly;
Nebius API keys are **never placed in arguments**. Launch Services does not promise
to inherit shell environment variables: use the existing Keychain item for this
launch path. Environment-first credentials still work when present in Coach's
own environment. Keychain service/account names and Nebius endpoint/prompts are
unchanged. macOS may ask you to allow the new Coach.app to read the existing item;
allow only this application. No stored key is recreated or logged by packaging.

Shutdown sends an authenticated local `/shutdown` request. Unity tracks the
actual app PID only after a matching launch nonce, and checks process start time
before any emergency termination. Unowned/manual Coach instances are not killed.
Stopping Editor Play Mode uses the same cleanup. A hung app that never completes
the ownership handshake is not killed by guessing a process name/PID.

## Grant permission manually

1. Stop Unity Play Mode and close any old development Coach first. Do not grant
   the Conda executable again as a substitute for granting the packaged app.
2. Keep Coach.app at a stable location. The default project `dist` location works;
   if moving it to `/Applications`, select that path in Unity's Packaged Coach Path
   field (otherwise an existing project `dist/Coach.app` takes priority).
3. Open **System Settings > Privacy & Security > Accessibility**. Use **+** and
   select the exact `Coach.app` above, enable its switch, then fully quit/relaunch
   Coach. Also grant Screen Recording to Coach.app for Mode 2's window capture.
   These permissions are separate; neither bundle metadata nor signing grants them.
4. Confirm the actual application process, without moving the mouse:

```sh
open -n -g -W /Users/james/UnityProjects/AI-Aim-Trainer/dist/Coach.app --args --diagnose-accessibility
cat "$HOME/Library/Logs/AI-Aim-Trainer/accessibility-diagnostic.json"
```

Expected: `frozen: true`, `bundle_identifier: com.ai-aim-trainer.coach`, executable
ending in `Coach.app/Contents/MacOS/Coach`, and
`coach_accessibility_trusted: true`. If false, the **app process** is still denied;
do not proceed with camera calibration or input. The diagnostic never prompts,
posts events, changes permission, captures the screen or reads the Nebius key.
Do not start a second normal app while diagnosing; this diagnostic exits by itself.

## Exact local tests

1. Optional offline bundle smoke test (no screen capture, mouse events, Keychain
   secret reads or Nebius calls):

```sh
open -n -g -W /Users/james/UnityProjects/AI-Aim-Trainer/dist/Coach.app --args --packaging-smoke-test
```

This briefly creates/collapses the existing Tk UI, binds loopback, instantiates
the explicit Keychain backend without reading credentials, writes a test telemetry
event, and runs bundled model inference on a blank image. Results are saved in
the same diagnostic JSON under `smoke_test`; inference does not enable assist.

2. Enter Unity Play. Confirm Console says **packaged Coach.app via Launch Services**
   and IPC ready. One collapsed AI widget should appear. The package log is
   `~/Library/Logs/AI-Aim-Trainer/coach-app.log`.
3. End Session. Confirm the existing report expands and analyzes the exported
   JSON. Allow Coach's Keychain access if macOS asks. This is a real Nebius request.
4. Verify permission is true first; only then follow `MODE2_SETUP.md` to verify
   camera response with RMB before enabling assistance. No input is sent by
   normal app launch, diagnostics or the smoke test.
5. Exit Play. Confirm the owned app closes. Manually launch Coach before entering
   Play again: Unity should connect, and exiting Play must leave that manual app
   running. Close it from Activity Monitor when done (the UI close minimizes).

Packaged resources are read-only. Packaged Coach prefers its bundled model even
when `--project-root` points to an unrelated standalone install directory.
**Standalone game windows use the full captured image automatically and require
no crop file.** The ROI adapts to actual captured pixels on Retina and on resize.
Unity Editor alone uses `yolo_dev/capture_region.editor.json` under the supplied
project root, or `~/Library/Application Support/AI-Aim-Trainer/capture_region.editor.json`
without a source project. Legacy `capture_region.json` remains supported only if
its `app` metadata is `Unity`; standalone-tagged configs are never used for Editor.
To create an independent Editor crop with the existing collector:

```sh
.venv/bin/python yolo_dev/capture_unity.py --window-id EDITOR_WINDOW_ID --select-region --config yolo_dev/capture_region.editor.json --preview-only
```

The current project `capture_region.json` is standalone-tagged and is left intact.
Reconfigure the Editor crop after
changing Unity layout/display. Runtime caches go to `~/Library/Caches/AI-Aim-Trainer`,
diagnostics/logs to `~/Library/Logs/AI-Aim-Trainer`, and correction JSONL remains
under its `assist` subdirectory. Do not edit/re-sign bundle contents after granting
permissions. Rebuilds must replace the entire signed app, never individual files.
