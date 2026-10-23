using UnityEngine;

// Mode 2 stays entirely inside this aim trainer. No input injection or firing.
public class AssistStatePublisher : MonoBehaviour
{
    [SerializeField, Range(1f, 45f)] private float coneDegrees = 25f;
    [SerializeField, Range(1f, 180f)] private float maxDegreesPerSecond = 65f;
    [SerializeField, Range(1f, 20f)] private float smoothing = 7f;
    public static AssistStatePublisher Instance { get; private set; }
    public bool Armed { get; private set; }
    public string Status { get; private set; } = "OFF";
    public bool ShotCorrection { get; private set; }
    private int lastCommand = -1;
    private float leaseUntil;
    private bool remote;
    private void Awake() { Instance = this; }
    public void Command(bool enabled, int sequence, string mode = "hold")
    {
        if (!enabled) { if (remote || (lastCommand >= 0 && sequence != lastCommand)) Stop(); lastCommand = sequence; return; }
        if (sequence != lastCommand) { Armed = true; remote = true; ShotCorrection = mode == "shot"; Status = "READY"; lastCommand = sequence; }
        leaseUntil = Time.realtimeSinceStartup + 0.6f;
    }
    public void Stop() { Armed = false; Status = "OFF"; }
    private void Update()
    {
        if (Armed && !ShotCorrection && !Input.GetMouseButton(1)) Status = "READY";
        if (Input.GetKey(KeyCode.F8) || Input.GetKey(KeyCode.Escape) ||
            (remote && Time.realtimeSinceStartup > leaseUntil)) Stop();
    }
    public void ApplyAssist(PlayerController player)
    {
        if (!CanAssist(player.PlayerCamera) || ShotCorrection || !Input.GetMouseButton(1)) return;
        Status = "READY";
        var camera = player.PlayerCamera;
        var nearest = FindHead(camera, player, float.PositiveInfinity);
        if (nearest == null) { Status = "NO VALID HEAD"; return; }
        Vector3 aim = nearest.GetComponent<Collider>().bounds.center - camera.transform.position;
        Vector3 angles = Quaternion.LookRotation(aim).eulerAngles;
        Vector2 error = new Vector2(Mathf.DeltaAngle(player.transform.eulerAngles.y, angles.y),
            Mathf.DeltaAngle(camera.transform.eulerAngles.x, angles.x));
        float dt = Mathf.Min(Time.deltaTime, 0.05f);
        Vector2 step = Vector2.ClampMagnitude(error * (1f - Mathf.Exp(-smoothing * dt)), maxDegreesPerSecond * dt);
        if (error.magnitude > 0.05f) player.ApplyAssistRotation(step);
        Status = "ASSISTING";
    }
    private bool CanAssist(Camera camera)
    {
        if (Input.GetKey(KeyCode.F8) || Input.GetKey(KeyCode.Escape) ||
            (remote && Time.realtimeSinceStartup > leaseUntil)) Stop();
        var session = SessionManager.Instance;
        var cursor = CursorStateManager.Instance;
        return Armed && Application.isFocused && camera != null && session != null && session.IsSessionActive &&
            !session.IsPaused && !session.IsSummaryOpen && cursor != null && cursor.GameplayInputEnabled &&
            Cursor.lockState == CursorLockMode.Locked && Time.timeScale > 0f;
    }
    // Called only by a manually initiated shot, immediately before the original hit test.
    public Ray CorrectShot(Camera camera, Ray original, float range)
    {
        if (!ShotCorrection || !CanAssist(camera) || !Input.GetMouseButtonDown(0)) return original;
        var head = FindHead(camera, camera.GetComponentInParent<PlayerController>(), range);
        if (head == null) { Status = "NO VALID HEAD"; return original; }
        Vector3 direction = head.GetComponent<Collider>().bounds.center - original.origin;
        if (direction.sqrMagnitude > range * range || Vector3.Angle(original.direction, direction) > coneDegrees) return original;
        Status = "SHOT CORRECTED";
        return new Ray(original.origin, direction.normalized);
    }
    private HitZone FindHead(Camera camera, PlayerController player, float range)
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
            if (direction.magnitude > range || Vector3.Angle(camera.transform.forward, direction) > coneDegrees) continue;
            // Ignore the player's own collider; reject heads occluded by any other surface.
            float distance = direction.magnitude;
            bool blocked = false;
            foreach (var hit in Physics.RaycastAll(camera.transform.position, direction.normalized, distance,
                ~0, QueryTriggerInteraction.Collide))
            {
                if (player != null && hit.collider.GetComponentInParent<PlayerController>() == player) continue;
                if (hit.collider.GetComponentInParent<Target>() != target) { blocked = true; break; }
            }
            if (!blocked && distance < best) { best = distance; nearest = head; }
        }
        return nearest;
    }
    private void OnApplicationFocus(bool focused) { if (!focused) Stop(); }
    private void OnDisable() { Stop(); if (Instance == this) Instance = null; }
}
