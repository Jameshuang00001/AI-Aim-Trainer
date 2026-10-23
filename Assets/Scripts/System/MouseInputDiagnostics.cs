using System;
using System.Globalization;
using System.IO;
using UnityEngine;

/// <summary>Temporary read-only input logging. F9 records 10 seconds; F10 changes
/// the manually assigned test label. Never injects input or changes the camera.</summary>
[DefaultExecutionOrder(1000)]
[RequireComponent(typeof(PlayerController))]
public class MouseInputDiagnostics : MonoBehaviour
{
    [SerializeField] private float recordSeconds = 10f;
    private PlayerController player;
    private StreamWriter writer;
    private float stopAt, nextConsole;
    private bool syntheticPhase;
    private Vector3 previousAngles;

    [Serializable] private class Sample
    {
        public string timestamp, phase, cursor;
        public int frame;
        public float realtime, axis_x, axis_y, raw_axis_x, raw_axis_y;
        public float consumed_x, consumed_y, yaw_delta, pitch_delta;
        public bool focused, gameplay, session_active, paused, look_processed, rmb;
    }

#if UNITY_EDITOR || DEVELOPMENT_BUILD
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void AttachInDevelopment()
    {
        PlayerController current = FindObjectOfType<PlayerController>();
        if (current != null && current.GetComponent<MouseInputDiagnostics>() == null)
            current.gameObject.AddComponent<MouseInputDiagnostics>();
    }
#endif

    private void Awake() { player = GetComponent<PlayerController>(); }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.F10))
        {
            syntheticPhase = !syntheticPhase;
            Debug.Log("Mouse diagnostic label: " + (syntheticPhase ? "synthetic_attempt" : "physical_baseline") +
                ". This is a manual test label, NOT automatic source identification.");
        }
        if (!Input.GetKeyDown(KeyCode.F9)) return;
        if (writer != null) { StopRecording(); return; }
        try
        {
            string directory = Path.Combine(Application.persistentDataPath, "mouse_input_diagnostics");
            Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) +
                "-" + Guid.NewGuid().ToString("N") + ".jsonl");
            writer = new StreamWriter(path) { AutoFlush = true };
            stopAt = Time.realtimeSinceStartup + Mathf.Max(1f, recordSeconds);
            nextConsole = 0f;
            previousAngles = player.PlayerCamera != null ? player.PlayerCamera.transform.eulerAngles : transform.eulerAngles;
            Debug.Log("Mouse diagnostics recording: " + path + ". F9 stops; F10 changes phase. Axis values are Unity input units, not HID counts.");
        }
        catch (Exception error) { Debug.LogWarning("Mouse diagnostics unavailable: " + error.GetType().Name); StopRecording(); }
    }

    private void LateUpdate()
    {
        if (writer == null) return;
        Vector3 angles = player.PlayerCamera != null ? player.PlayerCamera.transform.eulerAngles : transform.eulerAngles;
        SessionManager session = SessionManager.Instance;
        bool processed = player.LastLookInputFrame == Time.frameCount;
        Sample sample = new Sample {
            timestamp = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            phase = syntheticPhase ? "synthetic_attempt" : "physical_baseline",
            frame = Time.frameCount, realtime = Time.realtimeSinceStartup,
            axis_x = Input.GetAxis("Mouse X"), axis_y = Input.GetAxis("Mouse Y"),
            raw_axis_x = Input.GetAxisRaw("Mouse X"), raw_axis_y = Input.GetAxisRaw("Mouse Y"),
            consumed_x = processed ? player.LastLookInput.x : 0f,
            consumed_y = processed ? player.LastLookInput.y : 0f,
            yaw_delta = Mathf.DeltaAngle(previousAngles.y, angles.y),
            pitch_delta = Mathf.DeltaAngle(previousAngles.x, angles.x),
            focused = Application.isFocused, cursor = Cursor.lockState.ToString(),
            gameplay = CursorStateManager.Instance != null && CursorStateManager.Instance.GameplayInputEnabled,
            session_active = session != null && session.IsSessionActive,
            paused = session != null && session.IsPaused, look_processed = processed,
            rmb = Input.GetMouseButton(1)
        };
        previousAngles = angles;
        try { writer.WriteLine(JsonUtility.ToJson(sample)); }
        catch (IOException) { Debug.LogWarning("Mouse diagnostic write failed."); StopRecording(); return; }
        if (Time.realtimeSinceStartup >= nextConsole)
        {
            nextConsole = Time.realtimeSinceStartup + 0.25f;
            Debug.Log("Mouse input diagnostic " + JsonUtility.ToJson(sample));
        }
        if (Time.realtimeSinceStartup >= stopAt) StopRecording();
    }

    private void StopRecording()
    {
        if (writer == null) return;
        try { writer.Dispose(); } catch (IOException) { }
        writer = null;
        Debug.Log("Mouse diagnostics stopped. No input was generated.");
    }
    private void OnDisable() { StopRecording(); }
}
