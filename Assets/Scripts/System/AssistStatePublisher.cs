using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Security.Cryptography;
using UnityEngine;

/// <summary>
/// Optional read-only Mode 2 safety/verification bridge. Attach to Player and
/// assign the gameplay camera (NOT an arms camera). Does not change input,
/// camera, transforms, hitboxes, cursor state, scores, or session behavior.
/// </summary>
public class AssistStatePublisher : MonoBehaviour
{
    [SerializeField] private Camera playerCamera;
    [SerializeField] private int coachStatePort = 8766;
    [Tooltip("Opt-in read-only telemetry for the isolated F5/F6/F7 Quartz diagnostic. No input is injected by Unity.")]
    [SerializeField] private bool publishQuartzDiagnostics = false;
    [SerializeField] private int quartzDiagnosticPort = 8767;
    [Header("Read-only UI Diagnostics (optional)")]
    [SerializeField] private SettingsMenuManager settingsMenu;
    [SerializeField] private UIManager uiManager;
    private UdpClient sender;
    private UdpClient diagnosticSender;
    private float nextSend;
    private int pid;
    private float axisSumX, axisSumY, rawSumX, rawSumY;
    private int axisNonzeroFrames;
    private float nextReferenceCheck;
    private string lastGameplayBlockers;
    // Repeat a bounded history so a lost UDP packet does not erase input evidence.
    private readonly Queue<MouseFrame> mouseFrames = new Queue<MouseFrame>();
    private Vector3 previousCameraAngles;
    private bool havePreviousCameraAngles;
    private readonly string diagnosticStreamId = Guid.NewGuid().ToString("N");
    private int diagnosticBatch;
    private float nextPacketSizeLog;
    private readonly Dictionary<string, float> nextErrorLogs = new Dictionary<string, float>();
    // Base64 expands 3072 bytes to 4096. The complete envelope must stay <6000.
    private const int ChunkPayloadBytes = 3072;
    private const int MaxDiagnosticDatagramBytes = 6000;

    [Serializable]
    private class DiagnosticChunk
    {
        public int diagnostic_chunk_version = 1;
        public int pid, frame, batch_id, chunk_index, chunk_count, payload_bytes;
        public string stream_id, sha256, data;
    }

    [Serializable]
    private class MouseFrame
    {
        public int frame, input_sequence;
        public string timestamp;
        public double realtime;
        public float mouse_x, mouse_y, raw_x, raw_y, consumed_x, consumed_y;
        public float yaw, pitch, yaw_delta, pitch_delta;
        public bool look_processed, application_focused, cursor_locked;
    }

    [Serializable]
    private class State
    {
        public int pid;
        public bool gameplay, held, emergency;
        // Optional diagnostic detail. Older Coach readers ignore these fields.
        public int precondition_version;
        public bool application_focused, cursor_locked, session_present;
        public bool session_active, paused, gameplay_input_enabled;
        public bool cursor_manager_present, cursor_visible;
        public string cursor_lock_mode;
        public bool settings_manager_present, ui_manager_present;
        public bool settings_open, settings_panel_visible, summary_open;
        public bool summary_panel_visible, start_menu_visible;
        public string[] gameplay_blockers;
        public string sent_at_utc;
        public float unity_realtime, time_scale;
        public float yaw, pitch, fov, aspect, sensitivity;
        public int diagnostic_version, frame, axis_nonzero_frames;
        public float axis_sum_x, axis_sum_y, raw_sum_x, raw_sum_y;
        public int mouse_frame_version;
        public MouseFrame[] mouse_frames;
    }

    private void Awake()
    {
        pid = System.Diagnostics.Process.GetCurrentProcess().Id;
        try { sender = new UdpClient(); sender.Connect(IPAddress.Loopback, coachStatePort); }
        catch (SocketException error) { LogSendError("Coach socket initialization", 0, error); }
    }

    private void LateUpdate()
    {
        if (publishQuartzDiagnostics)
        {
            float x = Input.GetAxis("Mouse X"), y = Input.GetAxis("Mouse Y");
            axisSumX += x; axisSumY += y;
            rawSumX += Input.GetAxisRaw("Mouse X"); rawSumY += Input.GetAxisRaw("Mouse Y");
            Vector3 angles = playerCamera != null ? playerCamera.transform.eulerAngles : Vector3.zero;
            if (x != 0f || y != 0f)
            {
                axisNonzeroFrames++;
                PlayerController controller = GetComponent<PlayerController>();
                bool processed = controller != null && controller.LastLookInputFrame == Time.frameCount;
                mouseFrames.Enqueue(new MouseFrame {
                    frame = Time.frameCount, input_sequence = axisNonzeroFrames,
                    timestamp = DateTime.UtcNow.ToString("o"), realtime = Time.realtimeSinceStartupAsDouble,
                    mouse_x = x, mouse_y = y,
                    raw_x = Input.GetAxisRaw("Mouse X"), raw_y = Input.GetAxisRaw("Mouse Y"),
                    consumed_x = processed ? controller.LastLookInput.x : 0f,
                    consumed_y = processed ? controller.LastLookInput.y : 0f,
                    look_processed = processed, yaw = angles.y, pitch = angles.x,
                    yaw_delta = havePreviousCameraAngles ? Mathf.DeltaAngle(previousCameraAngles.y, angles.y) : 0f,
                    pitch_delta = havePreviousCameraAngles ? Mathf.DeltaAngle(previousCameraAngles.x, angles.x) : 0f,
                    application_focused = Application.isFocused,
                    cursor_locked = Cursor.lockState == CursorLockMode.Locked
                });
                while (mouseFrames.Count > 32) mouseFrames.Dequeue();
            }
            previousCameraAngles = angles;
            havePreviousCameraAngles = playerCamera != null;
            if (diagnosticSender == null)
            {
                try { diagnosticSender = new UdpClient(); diagnosticSender.Connect(IPAddress.Loopback, quartzDiagnosticPort); }
                catch (SocketException error) {
                    LogSendError("Diagnostic socket initialization", 0, error);
                    if (diagnosticSender != null) diagnosticSender.Close(); diagnosticSender = null;
                }
            }
        }
        if (sender == null || playerCamera == null || Time.realtimeSinceStartup < nextSend) return;
        nextSend = Time.realtimeSinceStartup + 0.04f;
        SessionManager session = SessionManager.Instance;
        CursorStateManager cursor = CursorStateManager.Instance;
        // Runtime-created settings can appear after Awake. Lookup is throttled
        // and includes hidden managers; it never changes their active state.
        if (Time.realtimeSinceStartup >= nextReferenceCheck)
        {
            nextReferenceCheck = Time.realtimeSinceStartup + 1f;
            if (settingsMenu == null) settingsMenu = FindObjectOfType<SettingsMenuManager>(true);
            if (uiManager == null) uiManager = FindObjectOfType<UIManager>(true);
        }
        PlayerController player = GetComponent<PlayerController>();
        State state = new State {
            pid = pid,
            precondition_version = 2,
            application_focused = Application.isFocused,
            cursor_locked = Cursor.lockState == CursorLockMode.Locked,
            session_present = session != null,
            session_active = session != null && session.IsSessionActive,
            paused = session != null && session.IsPaused,
            cursor_manager_present = cursor != null,
            gameplay_input_enabled = cursor != null && cursor.GameplayInputEnabled,
            cursor_visible = Cursor.visible,
            cursor_lock_mode = Cursor.lockState.ToString(),
            settings_manager_present = settingsMenu != null,
            ui_manager_present = uiManager != null,
            settings_open = settingsMenu != null && settingsMenu.IsSettingsOpen,
            settings_panel_visible = settingsMenu != null && settingsMenu.IsSettingsPanelVisible,
            summary_open = session != null && session.IsSummaryOpen,
            summary_panel_visible = uiManager != null && uiManager.IsSummaryPanelVisible,
            start_menu_visible = uiManager != null && uiManager.IsStartMenuVisible,
            sent_at_utc = DateTime.UtcNow.ToString("o"),
            unity_realtime = Time.realtimeSinceStartup,
            time_scale = Time.timeScale,
            held = Input.GetMouseButton(1),
            emergency = Input.GetKey(KeyCode.F8) || Input.GetKey(KeyCode.Escape),
            yaw = playerCamera.transform.eulerAngles.y,
            pitch = playerCamera.transform.eulerAngles.x,
            fov = playerCamera.fieldOfView,
            aspect = playerCamera.aspect,
            sensitivity = player != null ? player.MouseSensitivity : 0f,
            diagnostic_version = publishQuartzDiagnostics ? 1 : 0,
            frame = Time.frameCount, axis_nonzero_frames = axisNonzeroFrames,
            axis_sum_x = axisSumX, axis_sum_y = axisSumY, raw_sum_x = rawSumX, raw_sum_y = rawSumY
        };
        // Preserve the original gameplay gate exactly, using the same captured
        // values as the individual diagnostics so the packet is self-consistent.
        state.gameplay = state.application_focused && state.cursor_locked &&
            state.cursor_manager_present && state.gameplay_input_enabled &&
            state.session_present && state.session_active && !state.paused;
        state.gameplay_blockers = GetGameplayBlockers(state);
        if (publishQuartzDiagnostics)
        {
            string blockers = string.Join(",", state.gameplay_blockers);
            if (blockers != lastGameplayBlockers)
            {
                Debug.Log($"Assist diagnostics {state.sent_at_utc} frame={state.frame} " +
                    $"gameplay={state.gameplay} blockers=[{blockers}] " +
                    $"focus={state.application_focused} cursor={state.cursor_lock_mode} " +
                    $"session={state.session_active} paused={state.paused} " +
                    $"settings={state.settings_panel_visible} summary={state.summary_panel_visible}");
                lastGameplayBlockers = blockers;
            }
        }
        byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(state));
        try { sender.Send(bytes, bytes.Length); }
        catch (SocketException error) { LogSendError($"Coach UDP {coachStatePort}", bytes.Length, error); }
        if (publishQuartzDiagnostics && diagnosticSender != null)
        {
            // Keep larger diagnostic history off the normal Coach state port.
            state.mouse_frame_version = 1;
            state.mouse_frames = mouseFrames.ToArray();
            bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(state));
            SendDiagnosticChunks(bytes, state.frame);
        }
    }

    private void SendDiagnosticChunks(byte[] payload, int frame)
    {
        if (payload.Length > 65536)
        {
            Debug.LogError($"Quartz diagnostic payload rejected: serialized_bytes={payload.Length}, limit=65536.");
            return;
        }
        int count = Math.Max(1, (payload.Length + ChunkPayloadBytes - 1) / ChunkPayloadBytes);
        int batch = ++diagnosticBatch;
        string digest;
        using (SHA256 hash = SHA256.Create())
            digest = BitConverter.ToString(hash.ComputeHash(payload)).Replace("-", "").ToLowerInvariant();
        int minBytes = int.MaxValue, maxBytes = 0;
        bool logSizes = Time.realtimeSinceStartup >= nextPacketSizeLog;
        for (int i = 0; i < count; i++)
        {
            int length = Math.Min(ChunkPayloadBytes, payload.Length - i * ChunkPayloadBytes);
            DiagnosticChunk chunk = new DiagnosticChunk {
                pid = pid, frame = frame, batch_id = batch, stream_id = diagnosticStreamId,
                chunk_index = i, chunk_count = count, payload_bytes = payload.Length,
                sha256 = digest, data = Convert.ToBase64String(payload, i * ChunkPayloadBytes, length)
            };
            byte[] datagram = Encoding.UTF8.GetBytes(JsonUtility.ToJson(chunk));
            minBytes = Math.Min(minBytes, datagram.Length);
            maxBytes = Math.Max(maxBytes, datagram.Length);
            // Measure the actual encoded envelope, not an estimate of its content.
            if (datagram.Length >= MaxDiagnosticDatagramBytes)
            {
                Debug.LogError($"Quartz diagnostic chunk rejected: bytes={datagram.Length}, limit={MaxDiagnosticDatagramBytes}.");
                return;
            }
            try { diagnosticSender.Send(datagram, datagram.Length); }
            catch (SocketException error) { LogSendError($"Quartz UDP {quartzDiagnosticPort} chunk={i}/{count}", datagram.Length, error); }
        }
        if (logSizes)
        {
            Debug.Log($"Quartz UDP size: batch={batch} serialized_bytes={payload.Length} chunks={count} " +
                $"datagram_min_bytes={minBytes} datagram_max_bytes={maxBytes} limit={MaxDiagnosticDatagramBytes}");
            nextPacketSizeLog = Time.realtimeSinceStartup + 2f;
        }
    }

    private void LogSendError(string context, int bytes, SocketException error)
    {
        // Rate-limit console output, but include the real error and byte count.
        string channel = context.StartsWith("Coach") ? "Coach" : "Quartz";
        float nextLog;
        if (nextErrorLogs.TryGetValue(channel, out nextLog) && Time.realtimeSinceStartup < nextLog) return;
        Debug.LogWarning($"{context} failed: bytes={bytes}, socket_error={error.SocketErrorCode}, " +
            $"native_error={error.ErrorCode}, message={error.Message}");
        nextErrorLogs[channel] = Time.realtimeSinceStartup + 2f;
    }

    private static string[] GetGameplayBlockers(State state)
    {
        // Only actual terms of the original gate belong here. Panel visibility
        // is separate evidence, not a replacement for session/cursor state.
        List<string> reasons = new List<string>();
        if (!state.application_focused) reasons.Add("application_not_focused");
        if (!state.cursor_locked) reasons.Add("cursor_not_locked");
        if (!state.cursor_manager_present) reasons.Add("cursor_manager_missing");
        else if (!state.gameplay_input_enabled) reasons.Add("gameplay_input_disabled");
        if (!state.session_present) reasons.Add("session_manager_missing");
        else
        {
            if (!state.session_active) reasons.Add("session_inactive");
            if (state.paused) reasons.Add("session_paused");
        }
        return reasons.ToArray();
    }

    private void OnDestroy()
    {
        if (sender != null) sender.Close();
        if (diagnosticSender != null) diagnosticSender.Close();
    }
}
