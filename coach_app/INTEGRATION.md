# Unity / Coach Integration (macOS)

## Standalone Setup

Keep the project folder containing both `coach_app` and `.venv`. Install Python
dependencies using `.venv/bin/python -m pip install -r coach_app/requirements.txt`.
That interpreter must include working Tk support.

Add CoachAppBridge to an active root GameObject and assign Coach Project Directory
to that folder before building. Alternatively set COACH_APP_ROOT in the game's
launch environment. If no bridge is present, Unity creates one automatically;
on macOS its default directory is alongside the standalone .app. No Python files
or virtual environment are embedded in the Unity build automatically.

Set NEBIUS_API_KEY in the environment inherited by Unity/the Coach. It is never
stored in scenes, code, IPC requests, or logs. Finder-launched apps do not normally
inherit Terminal exports; launch the game executable from your configured shell
or use an appropriately configured macOS launcher. The app does not read `.env`.

Startup probes 127.0.0.1:8765 and reuses an existing compatible Coach. Otherwise,
Unity starts `.venv/bin/python coach_app/main.py` with a private IPC token and
hidden window. It never starts a second instance on a port already owned by Coach.
Keep one standalone game active per port; configure another port for independent
games. A reused manually started Coach is never terminated by Unity.

## Editor Setup

Entering Play Mode automatically launches Coach using the Unity project's
`.venv/bin/python`, with no visible Terminal. No Inspector setup is required for
the standard project layout. An explicit Coach Project Directory or COACH_APP_ROOT
overrides the default. Readiness checks retry asynchronously for about 12 seconds;
the game does not wait on a blocking sleep and End Session notifications wait for
startup to finish.

Exiting Play Mode stops only the child process this bridge launched. Editor
assembly reload also cleans up the owned process. Manually started instances are
reused and left running. To test reuse, run `.venv/bin/python coach_app/main.py`
before Play. The default manual port is 8765, with no token.
For token-protected manual use, set COACH_IPC_TOKEN to the
same value in both the Unity launch environment and the Python environment.
Set COACH_IPC_PORT for manual Coach and the bridge's IPC Port to use another port.

Unity and the child inherit NEBIUS_API_KEY from Unity's process environment.
Setting it in a separate Terminal after the Editor is already running does not
update that environment: restart Unity from an environment with the key set.
The health response exposes only a boolean indicating key availability; Unity
warns when it is unavailable, without displaying the key. JSON and IPC still work.

## Flow and Safety

End Session exports JSON successfully first, then sends its absolute path to
`POST /analyze`. The Coach queues GUI work, brings its own window forward, and
runs the existing Nebius analysis off the GUI thread. No stats go over IPC: only
the file path. The only remote session-data request remains Nebius analysis.
Requests bind to IPv4 loopback; browser-origin commands are rejected.
Unity uses an asynchronous .NET HTTP client with proxies and redirects disabled
for this fixed loopback destination. Unity's global insecure-HTTP setting is not
changed. IPC waiting continues while the summary pauses scaled gameplay time.

Closing the Coach window hides it; it continues listening. While an analysis is
in flight, newer requests queue the most recent path for analysis afterward.
There is no new live capture, gameplay automation, or input injection.
Unity's Summary stays a resumable overlay with scores/targets intact. Escape
in Unity closes it and resumes gameplay. Closing Coach does not close Unity's
summary. Switch back to Unity to use its Escape handling.

macOS activation uses Tk plus a request to foreground the Coach's own PID.
If macOS denies activation, the window is still deiconified/raised; OS focus rules
can require allowing that activation. No Unity window is manipulated by Python.

On normal standalone quit or Play Mode exit, Unity kills only the Process object it launched.
It does not search by name or kill a manually started Coach. Forced OS termination
of Unity cannot guarantee a cleanup callback. On IPC/launch/export failure,
Unity logs a warning and gameplay still works; saved JSON can be opened manually.

## Checks

1. Launch standalone: one hidden Coach process, including after scene changes.
2. Shoot, End Session: saved path logs before Coach displays/analyzes new stats.
3. Close Coach window, return to Unity, Escape: gameplay and scores continue.
4. End Session again: same Coach window reappears, no second process.
5. Quit game: owned Coach exits. Repeat with manual Coach: manual Coach survives.
6. Missing Python/Tk, stopped Coach, invalid token or absent API key: clear warning
   or Coach error, never reset gameplay. API credentials are never logged.
7. Enter/exit Play Mode twice: each entry starts one owned Coach; each exit stops
   that child. Start Coach manually, enter/exit Play Mode: manual Coach survives.
