using UnityEngine;
using System;
using System.Collections.Generic;

// Mode 2 stays entirely inside this aim trainer. No input injection or firing.
public class AssistStatePublisher : MonoBehaviour
{
    [SerializeField, Range(1f, 45f)] private float coneDegrees = 25f;
    [SerializeField, Range(1f, 180f)] private float maxDegreesPerSecond = 65f;
    [SerializeField, Range(1f, 20f)] private float smoothing = 7f;
    public static AssistStatePublisher Instance { get; private set; }
    public bool Armed { get; private set; }
    public string Status { get; private set; } = "OFF";
    public float AssistSpeed => maxDegreesPerSecond;
    private double acquisitionStarted;
    public bool ProximityAssist { get; private set; }
    private float proximityDegrees = 3f;
    [Serializable] public class CalibrationSample
    {
        public string target_id, mode, started_at_utc, end_reason;
        public float speed_deg_per_second, zone_radius_deg, duration_ms, path_length_deg;
        public float time_to_settle_ms = -1f;
        public float initial_yaw_error_deg, initial_pitch_error_deg, initial_error_deg;
        public float applied_yaw_deg, applied_pitch_deg, remaining_error_deg;
    }
    public readonly List<CalibrationSample> Calibration = new List<CalibrationSample>();
    private HitZone activeHead;
    private CalibrationSample activeSample;
    public string Feedback => Calibration.Count == 0 ? "No corrections yet" :
        string.Format(System.Globalization.CultureInfo.InvariantCulture,
        "Corrections {0} | Last entry {1:F2} deg | Applied yaw {2:F2}, pitch {3:F2} deg | Residual {4:F2} deg",
        Calibration.Count, Calibration[Calibration.Count-1].initial_error_deg,
        Calibration[Calibration.Count-1].applied_yaw_deg, Calibration[Calibration.Count-1].applied_pitch_deg,
        Calibration[Calibration.Count-1].remaining_error_deg);
    public void FinishCalibration(string reason)
    {
        if (activeSample != null)
        {
            activeSample.duration_ms = (float)((Time.realtimeSinceStartupAsDouble - acquisitionStarted) * 1000);
            activeSample.end_reason = reason;
        }
        activeHead = null; activeSample = null;
    }
    public void ResetCalibration() { FinishCalibration("reset"); Calibration.Clear(); }
    private int lastCommand = -1;
    private float leaseUntil;
    private bool remote;
    private void Awake() { Instance = this; }
    public void Command(bool enabled, int sequence, string mode = "hold", float radius = 3f, float speed = 65f)
    {
        if (!enabled) { if (remote || (lastCommand >= 0 && sequence != lastCommand)) Stop(); lastCommand = sequence; return; }
        float requestedSpeed = float.IsNaN(speed) || float.IsInfinity(speed) ? 65f : Mathf.Clamp(speed, 5f, 180f);
        if (!Mathf.Approximately(requestedSpeed, maxDegreesPerSecond)) FinishCalibration("speed_changed");
        maxDegreesPerSecond = requestedSpeed;
        if (sequence != lastCommand) { Armed = true; remote = true; ProximityAssist = mode == "proximity"; proximityDegrees = float.IsNaN(radius) || float.IsInfinity(radius) ? 3f : Mathf.Clamp(radius, 0.5f, 10f); Status = "READY"; lastCommand = sequence; }
        leaseUntil = Time.realtimeSinceStartup + 0.6f;
    }
    public void Stop() { Armed = false; Status = "OFF"; FinishCalibration("stopped"); }
    private void Update()
    {
        if (Armed && !ProximityAssist && !Input.GetMouseButton(1)) Status = "READY";
        if (Input.GetKey(KeyCode.F8) || Input.GetKey(KeyCode.Escape) ||
            (remote && Time.realtimeSinceStartup > leaseUntil)) Stop();
    }
    public void ApplyAssist(PlayerController player)
    {
        if (!CanAssist(player.PlayerCamera) || (!ProximityAssist && !Input.GetMouseButton(1)))
        { FinishCalibration("input_gate_or_release"); return; }
        Status = "READY";
        var camera = player.PlayerCamera;
        var nearest = FindHead(camera, player, ProximityAssist ? proximityDegrees : coneDegrees);
        if (nearest == null) { Status = ProximityAssist ? "OUTSIDE ASSIST ZONE" : "NO VALID HEAD"; FinishCalibration("left_zone_or_invalid_target"); return; }
        Vector3 aim = nearest.GetComponent<Collider>().bounds.center - camera.transform.position;
        Vector3 angles = Quaternion.LookRotation(aim).eulerAngles;
        Vector2 error = new Vector2(Mathf.DeltaAngle(player.transform.eulerAngles.y, angles.y),
            Mathf.DeltaAngle(camera.transform.eulerAngles.x, angles.x));
        if (activeHead != nearest)
        {
            FinishCalibration("target_changed");
            acquisitionStarted = Time.realtimeSinceStartupAsDouble;
            activeHead = nearest;
            activeSample = new CalibrationSample { target_id = nearest.TargetParent.TargetId,
                mode = ProximityAssist ? "proximity" : "hold", started_at_utc = DateTime.UtcNow.ToString("O"),
                speed_deg_per_second = maxDegreesPerSecond, zone_radius_deg = ProximityAssist ? proximityDegrees : coneDegrees,
                end_reason = "tracking", initial_yaw_error_deg = error.x,
                initial_pitch_error_deg = error.y, initial_error_deg = error.magnitude };
            Calibration.Add(activeSample);
        }
        float dt = Mathf.Min(Time.deltaTime, 0.05f);
        Vector2 step = Vector2.ClampMagnitude(error * (1f - Mathf.Exp(-smoothing * (maxDegreesPerSecond / 65f) * dt)), maxDegreesPerSecond * dt);
        Vector3 before = camera.transform.eulerAngles;
        if (error.magnitude > 0.05f) player.ApplyAssistRotation(step);
        Vector3 after = camera.transform.eulerAngles;
        activeSample.applied_yaw_deg += Mathf.DeltaAngle(before.y, after.y);
        activeSample.applied_pitch_deg += Mathf.DeltaAngle(before.x, after.x);
        activeSample.remaining_error_deg = Vector3.Angle(camera.transform.forward, aim);
        activeSample.path_length_deg += new Vector2(Mathf.DeltaAngle(before.y, after.y), Mathf.DeltaAngle(before.x, after.x)).magnitude;
        activeSample.duration_ms = (float)((Time.realtimeSinceStartupAsDouble - acquisitionStarted) * 1000);
        if (activeSample.remaining_error_deg <= 0.1f && activeSample.time_to_settle_ms < 0f)
            activeSample.time_to_settle_ms = activeSample.duration_ms;
        Status = "ASSISTING";
    }
    private bool CanAssist(Camera camera)
    {
        if (Input.GetKey(KeyCode.F8) || Input.GetKey(KeyCode.Escape) ||
            (remote && Time.realtimeSinceStartup > leaseUntil)) Stop();
        var session = SessionManager.Instance;
        var cursor = CursorStateManager.Instance;
        return Armed && Application.isFocused && camera != null && session != null && session.IsSessionActive &&
            !session.IsPaused && !session.IsSummaryOpen && cursor != null && cursor.CanReadGameplayInput &&
            Cursor.lockState == CursorLockMode.Locked && Time.timeScale > 0f;
    }
    private HitZone FindHead(Camera camera, PlayerController player, float limitDegrees)
    {
        HitZone nearest = null;
        float best = float.PositiveInfinity;
        foreach (var head in FindObjectsOfType<HitZone>())
        {
            var target = head.TargetParent;
            var collider = head.GetComponent<Collider>();
            if (!head.isActiveAndEnabled || head.Zone != HitZoneType.Head || target == null ||
                !target.isActiveAndEnabled || !target.IsHittable || collider == null || !collider.enabled) continue;
            Vector3 point = collider.bounds.center;
            Vector3 viewport = camera.WorldToViewportPoint(point);
            if (viewport.z <= camera.nearClipPlane || viewport.x < 0 || viewport.x > 1 || viewport.y < 0 || viewport.y > 1) continue;
            Vector3 direction = point - camera.transform.position;
            if (Vector3.Angle(camera.transform.forward, direction) > limitDegrees) continue;
            // Ignore the player's own collider; reject heads occluded by any other surface.
            float distance = direction.magnitude;
            bool blocked = false;
            foreach (var hit in Physics.RaycastAll(camera.transform.position, direction.normalized, distance,
                ~0, QueryTriggerInteraction.Collide))
            {
                if (player != null && hit.collider.GetComponentInParent<PlayerController>() == player) continue;
                if (hit.collider.GetComponentInParent<Target>() != target) { blocked = true; break; }
            }
            float rank = ProximityAssist ? Vector3.Angle(camera.transform.forward, direction) : distance;
            if (!blocked && rank < best) { best = rank; nearest = head; }
        }
        return nearest;
    }
    private void OnApplicationFocus(bool focused) { if (!focused) Stop(); }
    private void OnDisable() { Stop(); if (Instance == this) Instance = null; }
}
