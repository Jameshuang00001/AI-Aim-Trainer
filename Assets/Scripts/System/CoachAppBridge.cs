using System;
using System.Collections;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Net.Http;
using UnityEngine;
using Debug = UnityEngine.Debug;

/// <summary>Owns at most one Coach process; all communication stays on loopback.</summary>
public class CoachAppBridge : MonoBehaviour
{
    [Tooltip("Folder containing coach_app and .venv. Set this for standalone builds, or set COACH_APP_ROOT.")]
    [SerializeField] private string coachProjectDirectory;
    [Tooltip("Optional absolute Coach.app path on macOS. Otherwise checks project dist/Coach.app, then /Applications/Coach.app.")]
    [SerializeField] private string packagedCoachPath;
    [SerializeField, Range(1024, 65535)] private int ipcPort = 8765;
    private static CoachAppBridge instance;
    private Process ownedProcess;
    private Process ownedAppProcess;
    private DateTime ownedAppStartTime;
    private string ownedLaunchId;
    private bool launchedPackaged;
    private string token;
    private bool connected;
    private bool initializing;
    private bool shuttingDown;
    private HttpClient http;
    private string BaseUrl => "http://127.0.0.1:" + ipcPort;

    [Serializable] private class Health
    {
        public string app = "";
        public int protocol = 0;
        public bool api_key_available = false;
        public bool api_key_checked = false;
        public string launch_id = "";
        public int process_id;
    }
    [Serializable] private class AnalyzeCommand { public string path; }

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Bootstrap()
    {
        if (instance == null)
        {
            CoachAppBridge existing = FindObjectOfType<CoachAppBridge>();
            if (existing == null) new GameObject("CoachAppBridge").AddComponent<CoachAppBridge>();
        }
    }

    private void Awake()
    {
        if (instance != null && instance != this) { Destroy(this); return; }
        instance = this;
        DontDestroyOnLoad(gameObject);
        token = Environment.GetEnvironmentVariable("COACH_IPC_TOKEN") ?? "";
#if UNITY_EDITOR
        UnityEditor.EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
        UnityEditor.AssemblyReloadEvents.beforeAssemblyReload += StopOwnedCoach;
#endif
        // A fixed loopback client bypasses proxies and never follows redirects.
        // Do not relax Unity's global insecure-HTTP policy for local IPC.
        http = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false })
        {
            Timeout = TimeSpan.FromSeconds(3)
        };
    }

    [Serializable] private class AssistCommand { public bool enabled; public int sequence; public string mode; public float radius = 3f; public float speed = 65f; }
    private IEnumerator PollAssist()
    {
        while (!shuttingDown)
        {
            var assist = AssistStatePublisher.Instance;
            string status = assist == null ? "OFF" : assist.Status;
            var request = new HttpRequestMessage(HttpMethod.Get, BaseUrl + "/assist?status=" + Uri.EscapeDataString(status) + "&feedback=" + Uri.EscapeDataString(assist == null ? "" : assist.Feedback));
            request.Headers.Add("X-Coach-Token", token);
            var pending = http.SendAsync(request);
            while (!pending.IsCompleted && !shuttingDown) yield return null;
            if (pending.IsCompleted && !pending.IsFaulted && !pending.IsCanceled)
            {
                using (var response = pending.Result)
                {
                    if (response.IsSuccessStatusCode)
                    {
                        var body = response.Content.ReadAsStringAsync();
                        while (!body.IsCompleted) yield return null;
                        if (!body.IsFaulted && !body.IsCanceled)
                        {
                            AssistCommand command = null;
                            try { command = JsonUtility.FromJson<AssistCommand>(body.Result); }
                            catch (ArgumentException) { }
                            if (command != null && AssistStatePublisher.Instance != null)
                                AssistStatePublisher.Instance.Command(command.enabled, command.sequence, command.mode, command.radius, command.speed);
                        }
                    }
                }
            }
            request.Dispose();
            yield return new WaitForSecondsRealtime(0.1f);
        }
    }

    private IEnumerator Start()
    {
        yield return Initialize();
        if (connected) yield return ShowCoach();
        StartCoroutine(PollAssist());
    }

    private IEnumerator ShowCoach()
    {
        using (var request = new HttpRequestMessage(HttpMethod.Post, BaseUrl + "/show"))
        {
            request.Headers.Add("X-Coach-Token", token);
            var pending = http.SendAsync(request);
            while (!pending.IsCompleted) yield return null;
            if (!pending.IsFaulted && !pending.IsCanceled) pending.Result.Dispose();
        }
    }

    private IEnumerator CheckHealth()
    {
        connected = false;
        var pending = http.GetAsync(BaseUrl + "/health?startup=1");
        while (!pending.IsCompleted) yield return null;
        if (pending.IsFaulted || pending.IsCanceled) yield break;
        using (HttpResponseMessage response = pending.Result)
        {
            if (!response.IsSuccessStatusCode) yield break;
            var body = response.Content.ReadAsStringAsync();
            while (!body.IsCompleted) yield return null;
            if (body.IsFaulted || body.IsCanceled) yield break;
            Health health = null;
            try { health = JsonUtility.FromJson<Health>(body.Result); }
            catch (ArgumentException) { }
            connected = health != null && health.app == "aim-trainer-coach" && health.protocol == 1;
            // Launch Services owns the app PID; `open -W` is only our waiter.
            // Claim an app only when it identifies this specific launch nonce.
            if (connected && launchedPackaged && ownedAppProcess == null &&
                !string.IsNullOrEmpty(ownedLaunchId) && health.launch_id == ownedLaunchId && health.process_id > 0)
            {
                try {
                    ownedAppProcess = Process.GetProcessById(health.process_id);
                    ownedAppStartTime = ownedAppProcess.StartTime;
                }
                catch (Exception) { ownedAppProcess = null; }
            }
            if (connected)
            {
                Debug.Log("Coach IPC ready (" + (ownedProcess != null && !ownedProcess.HasExited ? "owned process" : "existing process") + ").");
                if (health.api_key_checked && !health.api_key_available)
                    Debug.LogWarning("Coach: no Nebius key is available from the environment or macOS Keychain. Run .venv/bin/python -m coach_app.credentials setup, or unlock/allow Keychain access. JSON/IPC still work.");
            }
        }
    }

    private IEnumerator Initialize()
    {
        if (shuttingDown) yield break;
        if (initializing) { while (initializing) yield return null; yield break; }
        initializing = true;
        yield return CheckHealth();
        if (!connected && !shuttingDown)
        {
            if (ownedProcess == null || ownedProcess.HasExited)
            {
                // A previous exited child must never be mistaken for an active owner.
                StopOwnedCoach();
                LaunchCoach();
            }
            float deadline = Time.realtimeSinceStartup + 12f;
            while (!connected && !shuttingDown && ownedProcess != null && Time.realtimeSinceStartup < deadline)
            {
                if (ownedProcess.HasExited)
                {
                    int exitCode = ownedProcess.ExitCode;
                    StopOwnedCoach();
                    // A simultaneous manual launch may win the port. Its process is
                    // not ours: restore the configured token and probe until ready.
                    token = Environment.GetEnvironmentVariable("COACH_IPC_TOKEN") ?? "";
                    if (exitCode != 0)
                        Debug.LogWarning("Coach exited during startup (code " + exitCode + "). Check .venv Tk support and installed requirements.");
                }
                yield return new WaitForSecondsRealtime(0.25f);
                yield return CheckHealth();
                // Continue probing a concurrent/manual startup even if our child exits.
                if (ownedProcess == null && !connected)
                {
                    while (!connected && !shuttingDown && Time.realtimeSinceStartup < deadline)
                    {
                        yield return new WaitForSecondsRealtime(0.25f);
                        yield return CheckHealth();
                    }
                }
            }
        }
        initializing = false;
        if (!connected)
            Debug.LogWarning("Coach startup/connection timed out. Check Coach project path, .venv Python/Tk support, installed requirements and IPC port. Gameplay continues; a manual Coach is still supported.");
    }

    private void LaunchCoach()
    {
        string root = coachProjectDirectory;
        if (string.IsNullOrWhiteSpace(root)) root = Environment.GetEnvironmentVariable("COACH_APP_ROOT");
        if (string.IsNullOrWhiteSpace(root)) root = Application.isEditor
            ? Path.GetDirectoryName(Application.dataPath)
            : Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
        string hint = Path.Combine(Application.streamingAssetsPath, "coach-root.txt");
        if (!Application.isEditor && string.IsNullOrWhiteSpace(coachProjectDirectory) &&
            string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("COACH_APP_ROOT")) && File.Exists(hint))
        {
            string candidate = File.ReadAllText(hint).Trim();
            if (File.Exists(Path.Combine(candidate, "coach_app", "main.py"))) root = candidate;
        }
        // Local builds can sit below build/Mode2; find the source Coach above them.
        if (string.IsNullOrWhiteSpace(coachProjectDirectory) &&
            string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("COACH_APP_ROOT")))
        {
            var candidate = new DirectoryInfo(root);
            for (int depth = 0; candidate != null && depth < 5; depth++, candidate = candidate.Parent)
                if (File.Exists(Path.Combine(candidate.FullName, "coach_app", "main.py")))
                { root = candidate.FullName; break; }
        }
        string python = Path.Combine(root, ".venv", "bin", "python");
        string main = Path.Combine(root, "coach_app", "main.py");
        string appPath = packagedCoachPath;
        bool macOS = Application.platform == RuntimePlatform.OSXEditor || Application.platform == RuntimePlatform.OSXPlayer;
        if (macOS && string.IsNullOrWhiteSpace(appPath))
        {
            appPath = Path.Combine(root, "dist", "Coach.app");
            if (!Directory.Exists(appPath)) appPath = "/Applications/Coach.app";
        }
        bool useApp = !File.Exists(main) && macOS && !string.IsNullOrWhiteSpace(appPath) &&
            File.Exists(Path.Combine(appPath, "Contents", "MacOS", "Coach"));
        if (!useApp && (!File.Exists(python) || !File.Exists(main)))
        {
            Debug.LogWarning("Coach launch skipped: configure Coach Project Directory (or COACH_APP_ROOT) containing .venv/bin/python and coach_app/main.py.");
            return;
        }
        token = Guid.NewGuid().ToString("N");
        ownedLaunchId = Guid.NewGuid().ToString("N");
        launchedPackaged = useApp;
        try
        {
            ProcessStartInfo info = new ProcessStartInfo
            {
                // Launch Services gives the packaged app its native application
                // identity. Do not execute its internal binary as a Python child.
                FileName = useApp ? "/usr/bin/open" : python,
                Arguments = useApp
                    ? "-n -g -W " + QuoteArgument(appPath) + " --args --ipc-port " + ipcPort +
                        " --ipc-token " + token + " --launch-id " + ownedLaunchId + " --project-root " + QuoteArgument(root)
                    : QuoteArgument(main),
                WorkingDirectory = Directory.Exists(root) ? root : Path.GetTempPath(),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            info.EnvironmentVariables["COACH_IPC_TOKEN"] = token;
            info.EnvironmentVariables["COACH_IPC_PORT"] = ipcPort.ToString();
            info.EnvironmentVariables["COACH_LAUNCH_ID"] = ownedLaunchId;
            info.EnvironmentVariables["COACH_APP_ROOT"] = root;
            info.EnvironmentVariables["COACH_START_HIDDEN"] = "0";
            info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            // API credentials are inherited from the environment, never stored here.
            // Python resolves Keychain credentials when Unity Hub has no API key
            // in its environment. Unity never reads or receives that secret.
            ownedProcess = Process.Start(info);
            Debug.Log("Started owned Coach using " + (useApp ? "packaged Coach.app via Launch Services" : "project .venv/bin/python") + "; waiting for IPC readiness.");
            // Drain both pipes without logging private session data or credentials.
            ownedProcess.BeginOutputReadLine();
            ownedProcess.BeginErrorReadLine();
        }
        catch (Exception error)
        {
            Debug.LogWarning("Coach launch failed (" + error.GetType().Name + "). Gameplay continues.");
        }
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    public static void NotifySession(string path)
    {
        if (instance == null) Bootstrap();
        if (instance != null) instance.StartCoroutine(instance.SendSession(path));
    }

    private IEnumerator SendSession(string path)
    {
        if (initializing) while (initializing) yield return null;
        if (!connected) yield return Initialize();
        if (!connected) yield break;
        using (HttpRequestMessage request = new HttpRequestMessage(HttpMethod.Post, BaseUrl + "/analyze"))
        {
            request.Content = new StringContent(JsonUtility.ToJson(new AnalyzeCommand { path = path }), Encoding.UTF8, "application/json");
            request.Headers.Add("X-Coach-Token", token);
            var pending = http.SendAsync(request);
            while (!pending.IsCompleted) yield return null;
            if (pending.IsFaulted || pending.IsCanceled)
            {
                connected = false;
                Debug.LogWarning("Coach notification could not connect or timed out. JSON is saved; gameplay continues.");
                yield break;
            }
            using (HttpResponseMessage response = pending.Result)
            {
                if (!response.IsSuccessStatusCode)
                {
                    connected = false;
                    Debug.LogWarning("Coach notification failed (HTTP " + (int)response.StatusCode + "). Check the manual Coach token/port or process. JSON is saved; gameplay continues.");
                }
            }
        }
    }

    private void StopOwnedCoach()
    {
        // Never search by process name or kill a manually started/shared Coach.
        if (ownedProcess == null) return;
        if (!string.IsNullOrEmpty(ownedLaunchId) && http != null)
        {
            try {
                using (var request = new HttpRequestMessage(HttpMethod.Post, BaseUrl + "/shutdown"))
                {
                    request.Headers.Add("X-Coach-Token", token);
                    var pending = http.SendAsync(request);
                    if (pending.Wait(1200)) pending.Result.Dispose();
                }
            }
            catch (Exception) { }
        }
        if (ownedAppProcess != null)
        {
            try {
                if (!ownedAppProcess.WaitForExit(700))
                {
                    // Protect against PID reuse: never kill by name or an old PID alone.
                    using (Process current = Process.GetProcessById(ownedAppProcess.Id))
                        if (current.StartTime == ownedAppStartTime) current.Kill();
                }
            }
            catch (Exception) { }
            ownedAppProcess.Dispose();
            ownedAppProcess = null;
        }
        try { if (!ownedProcess.HasExited) ownedProcess.Kill(); }
        catch (Exception) { }
        ownedProcess.Dispose();
        ownedProcess = null;
        ownedLaunchId = null;
        launchedPackaged = false;
    }

    private void OnApplicationQuit() { shuttingDown = true; StopOwnedCoach(); }
#if UNITY_EDITOR
    private void OnPlayModeStateChanged(UnityEditor.PlayModeStateChange state)
    {
        if (state != UnityEditor.PlayModeStateChange.ExitingPlayMode) return;
        shuttingDown = true;
        StopOwnedCoach();
    }
#endif
    private void OnDestroy()
    {
        if (instance != this) return;
        shuttingDown = true;
#if UNITY_EDITOR
        UnityEditor.EditorApplication.playModeStateChanged -= OnPlayModeStateChanged;
        UnityEditor.AssemblyReloadEvents.beforeAssemblyReload -= StopOwnedCoach;
#endif
        StopOwnedCoach();
        if (http != null) http.Dispose();
        instance = null;
    }
}
