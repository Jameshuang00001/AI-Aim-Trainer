# Unity / Coach Integration (macOS)

## Standalone Setup

The preferred macOS launcher now uses a packaged Coach.app through Launch Services
when available; see [MACOS_APP.md](MACOS_APP.md) for build, bundle identity, permissions
and ownership testing. The Python setup below remains the development fallback.

Keep the project folder containing both `coach_app` and `.venv`. Install Python
dependencies using `.venv/bin/python -m pip install -r coach_app/requirements.txt`.
That interpreter must include working Tk support.

Add CoachAppBridge to an active root GameObject and assign Coach Project Directory
to that folder before building. Alternatively set COACH_APP_ROOT in the game's
launch environment. If no bridge is present, Unity creates one automatically;
on macOS its default directory is alongside the standalone .app. No Python files
or virtual environment are embedded in the Unity build automatically.

Set up the key once using `.venv/bin/python -m coach_app.credentials setup`.
It is stored in macOS Keychain, not in project files. See README.md for details.
Coach checks NEBIUS_API_KEY first, then Keychain, so Unity Hub/Finder launches no
longer depend on Terminal exports. The key is never stored in scenes, code, IPC
requests, or logs. The app does not read `.env`.

Startup probes 127.0.0.1:8765 and reuses an existing compatible Coach. Otherwise,
Unity starts packaged Coach.app if available, otherwise
`.venv/bin/python coach_app/main.py`, with a private IPC token and
collapsed floating widget. It never starts a second instance on a port already owned by Coach.
Keep one standalone game active per port; configure another port for independent
games. A reused manually started Coach is never terminated by Unity.

## Editor Setup

Entering Play Mode automatically launches packaged Coach.app when available, or
the Unity project's `.venv/bin/python`, with no visible Terminal. No Inspector setup is required for
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

An inherited NEBIUS_API_KEY still takes precedence, but is no longer required
on macOS after Keychain setup. The Python child retrieves the Keychain credential;
Unity never reads it. Health exposes availability and a safe credential error,
never the key. Unity warns only when neither source is available or accessible.
JSON and IPC still work when AI credentials are unavailable.

## Flow and Safety

End Session exports JSON successfully first, then sends its absolute path to
`POST /analyze`. The Coach queues GUI work, brings its own window forward, and
runs the existing Nebius analysis off the GUI thread. No stats go over IPC: only
the file path. The only remote session-data request remains Nebius analysis.
Requests bind to IPv4 loopback; browser-origin commands are rejected.
Unity uses an asynchronous .NET HTTP client with proxies and redirects disabled
for this fixed loopback destination. Unity's global insecure-HTTP setting is not
changed. IPC waiting continues while the summary pauses scaled gameplay time.

Closing/minimizing the Coach panel restores its 64x64 floating widget; it continues listening. While an analysis is
in flight, newer requests queue the most recent path for analysis afterward.
There is no new live capture, gameplay automation, or input injection.
Unity's Summary stays a resumable overlay with scores/targets intact. Escape
in Unity closes it and resumes gameplay. Closing Coach does not close Unity's
summary. Switch back to Unity to use its Escape handling.

The companion uses one frameless, always-on-top Tk root. Click the circular AI
widget to expand a 480x650 dark panel; drag the widget or panel header to move it.
The widget remembers its position for the current run. Ready, Analyzing, Report
Ready, and Error use a status dot plus expanded status text. Analysis continues
when minimized, and completion alone does not reopen a panel minimized by the user.
An incoming Unity notification does reopen the panel automatically.

The panel shows formatted session stats and a scrollable, four-section English
report. Analyze Latest uses the configured session path or the last IPC session's
directory; without either, it opens a JSON picker. Mode 1 is active; Mode 2 is
disabled and labeled Coming Soon. No aim assistance or live capture is implemented.

On macOS, install the Cocoa dependency from requirements.txt in the same .venv.
The Coach resolves only its own Tk root's NSWindow through AppKit and applies
NSFloatingWindowLevel, hidesOnDeactivate=false, mouse interaction enabled,
CanJoinAllSpaces, and FullScreenAuxiliary. The same window policy applies to both
widget and panel. It reapplies after mapping/layout changes and deactivation
events, not through a periodic lift/focus loop. No AppleScript, application
activation, forced keyboard focus, or Accessibility/Screen Recording permissions
are used. Collapsing never calls focus_force. No Unity window is modified.
If PyObjC is missing, a Terminal diagnostic explains how to install it; native
floating behavior is then unavailable. Fullscreen exclusive rendering and macOS
Spaces/window-manager rules may still impose limits and require build testing.
The old COACH_START_HIDDEN launch flag is accepted but no longer hides the widget.

On normal standalone quit or Play Mode exit, Unity kills only the Process object it launched.
It does not search by name or kill a manually started Coach. Forced OS termination
of Unity cannot guarantee a cleanup callback. On IPC/launch/export failure,
Unity logs a warning and gameplay still works; saved JSON can be opened manually.

## Checks

1. Launch standalone: one collapsed Coach widget, including after scene changes.
2. Shoot, End Session: saved path logs before Coach displays/analyzes new stats.
3. Close Coach window, return to Unity, Escape: gameplay and scores continue.
4. End Session again: same Coach window reappears, no second process.
5. Quit game: owned Coach exits. Repeat with manual Coach: manual Coach survives.
6. Missing Python/Tk, stopped Coach, invalid token or absent API key: clear warning
   or Coach error, never reset gameplay. API credentials are never logged.
7. Enter/exit Play Mode twice: each entry starts one owned Coach; each exit stops
   that child. Start Coach manually, enter/exit Play Mode: manual Coach survives.

Opt-in UI tests (briefly opens native windows, no API calls):
`COACH_GUI_TESTS=1 .venv/bin/python -m unittest coach_app.test_overlay -v`.
Tests cover widget clicks, drag versus click, panel bounds, mode disablement,
minimize during analysis, main-thread updates, and repeated simulated IPC events.
