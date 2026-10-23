# AI Aim Trainer Coach

## One-Time Nebius Keychain Setup (macOS)

From the Unity project root:

```sh
.venv/bin/python -m pip install -r coach_app/requirements.txt
.venv/bin/python -m coach_app.credentials setup
```

Enter your Nebius API key at the hidden prompt. Do not put the key in the command
itself, a Unity Inspector field, source code, or a repository file. The command
writes directly to macOS Keychain using its native backend, not a file or a
shell command containing the secret. It does not print the key.

The Keychain item uses service **AI Aim Trainer Coach** and account
**NEBIUS_API_KEY**. Re-run setup to replace it. You can manage/remove the item in
Keychain Access. Keep your login Keychain unlocked. macOS may ask you to allow
access for the project's trusted Python interpreter; approve it if appropriate.
This is a credential-access prompt, not Screen Recording or Accessibility access.

Restart the Coach once after setup (exit/re-enter Unity Play Mode for an owned
Coach). Unity Hub does not need an exported environment variable anymore.
No real key is included in this repository or written to `.env`.

## Credential Lookup

1. Use a nonempty `os.environ.get("NEBIUS_API_KEY")` first.
2. On macOS, otherwise query the Keychain item above.
3. If absent, locked, denied, or unavailable, show a clear error without crashing.

A stale environment key takes precedence over Keychain; unset it if you intend to
use Keychain. No key is sent to Unity or included in IPC health responses: health
reports only availability and a safe error message. The credential is sent only
as authentication to the existing Nebius API. API endpoint/model selection and
English-only report formatting are unchanged.

## Running

Unity prefers packaged `Coach.app` on macOS when present, otherwise automatically
launches `.venv/bin/python coach_app/main.py`, and uses the
existing floating widget and loopback IPC. End Session still exports JSON and
automatically opens/analyzes the report. Manual launch remains supported:

```sh
.venv/bin/python coach_app/main.py
```

See [INTEGRATION.md](INTEGRATION.md) for lifecycle and platform details.

## Optional Mode 2 Experiment

For the standalone macOS app, stable bundle identity, permission setup and Unity
launch behavior, see [MACOS_APP.md](MACOS_APP.md).

Mode 2: Head Lock is opt-in and OFF by default. It uses the local YOLO model,
requires holding RMB and verified Unity locked-cursor response, and never fires.
See [MODE2_SETUP.md](MODE2_SETUP.md) for the required read-only Unity publisher,
permissions, calibration, F8/Stop controls, telemetry location and test checklist.
It does not change Mode 1 analysis, credentials or the existing session IPC.

For isolated tagged Quartz event observation and the per-process listen-only tap,
see [QUARTZ_PROVENANCE.md](QUARTZ_PROVENANCE.md). Each bounded pulse requires a
fresh F6 press; the tool does not suppress local hardware input.

Tests mock all Keychain reads/writes; they do not access or change your real key:

```sh
.venv/bin/python -m unittest coach_app.test_credentials coach_app.test_nebius_client
```
