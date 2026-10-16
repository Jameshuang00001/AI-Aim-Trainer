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
    [SerializeField, Range(1024, 65535)] private int ipcPort = 8765;
    private static CoachAppBridge instance;
    private Process ownedProcess;
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

    private IEnumerator Start()
    {
        yield return Initialize();
    }

    private IEnumerator CheckHealth()
    {
        connected = false;
        var pending = http.GetAsync(BaseUrl + "/health");
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
            if (connected)
            {
                Debug.Log("Coach IPC ready (" + (ownedProcess != null && !ownedProcess.HasExited ? "owned process" : "existing process") + ").");
                if (!health.api_key_available)
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
        string python = Path.Combine(root, ".venv", "bin", "python");
        string main = Path.Combine(root, "coach_app", "main.py");
        if (!File.Exists(python) || !File.Exists(main))
        {
            Debug.LogWarning("Coach launch skipped: configure Coach Project Directory (or COACH_APP_ROOT) containing .venv/bin/python and coach_app/main.py.");
            return;
        }
        token = Guid.NewGuid().ToString("N");
        try
        {
            ProcessStartInfo info = new ProcessStartInfo
            {
                FileName = python,
                Arguments = "\"" + main.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            info.EnvironmentVariables["COACH_IPC_TOKEN"] = token;
            info.EnvironmentVariables["COACH_IPC_PORT"] = ipcPort.ToString();
            info.EnvironmentVariables["COACH_START_HIDDEN"] = "1";
            info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            // API credentials are inherited from the environment, never stored here.
            // Python resolves Keychain credentials when Unity Hub has no API key
            // in its environment. Unity never reads or receives that secret.
            ownedProcess = Process.Start(info);
            Debug.Log("Started owned Coach using project .venv/bin/python; waiting for IPC readiness.");
            // Drain both pipes without logging private session data or credentials.
            ownedProcess.BeginOutputReadLine();
            ownedProcess.BeginErrorReadLine();
        }
        catch (Exception error)
        {
            Debug.LogWarning("Coach launch failed (" + error.GetType().Name + "). Gameplay continues.");
        }
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
        try { if (!ownedProcess.HasExited) ownedProcess.Kill(); }
        catch (Exception) { }
        ownedProcess.Dispose();
        ownedProcess = null;
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
