using UnityEngine;

/// <summary>
/// Lightweight movement for aim trainer targets.
/// The target moves around the position where it spawned.
/// </summary>
public class TargetMovement : MonoBehaviour
{
    public enum MovementType
    {
        Horizontal,
        Vertical,
        Circular
    }

    [Header("Movement")]
    [SerializeField] private MovementType movementType = MovementType.Horizontal;
    [SerializeField] private float movementSpeed = 2f;
    [SerializeField] private float movementDistance = 2f;

    [Header("Randomness")]
    [SerializeField] private bool randomizeSpeed = true;
    [SerializeField] private float minSpeedMultiplier = 0.8f;
    [SerializeField] private float maxSpeedMultiplier = 1.2f;

    private Vector3 spawnLocalPosition;
    private float movementDirection = 1f;
    private float phaseOffset;
    private float speedMultiplier = 1f;
    private Animator targetAnimator;

    [Header("Humanoid Roaming")]
    [SerializeField] private bool randomRoaming = true;
    [SerializeField, Min(0.05f)] private float minMoveDuration = 1.2f;
    [SerializeField, Min(0.05f)] private float maxMoveDuration = 2.5f;
    [SerializeField, Min(0.05f)] private float minPauseDuration = 0.4f;
    [SerializeField, Min(0.05f)] private float maxPauseDuration = 1f;
    [SerializeField, Min(0f)] private float animatorMovingGraceTime = 0.25f;
    [SerializeField] private bool pauseCircularMovement;
    [SerializeField] private float turnSpeed = 540f;
    [SerializeField] private LayerMask groundLayers = ~0;

    private bool groundedHumanoid;
    private bool pausing;
    private float nextDecisionTime;
    private Vector3 spawnWorldPosition;
    private float groundOffset;
    private bool actuallyMoving;
    private Vector3 phaseStartPosition;
    private Vector3 phaseEndPosition;
    private float phaseStartTime;
    private float phaseDuration;
    private float lastMovementTime = float.NegativeInfinity;
    private float circleAngle;
    private bool initialized;

    private bool UsesRoaming => targetAnimator != null && groundedHumanoid && randomRoaming;

    public void SetGroundedHumanoid(bool grounded, float offset, LayerMask layers)
    {
        groundedHumanoid = grounded;
        groundOffset = offset;
        groundLayers = layers;
    }

    private void Awake()
    {
        targetAnimator = GetComponentInChildren<Animator>();
        if (targetAnimator != null) targetAnimator.applyRootMotion = false;
    }

    private void OnEnable()
    {
        lastMovementTime = float.NegativeInfinity;
        if (initialized) BeginMovePhase();
    }

    private void OnDisable()
    {
        // Death bypasses grace and stops walking immediately.
        lastMovementTime = float.NegativeInfinity;
        if (targetAnimator != null && targetAnimator.GetBool("IsMoving"))
            targetAnimator.SetBool("IsMoving", false);
    }

    private void UpdateMovementAnimation()
    {
        if (targetAnimator != null)
        {
            // Enabled targets with zero speed or distance should still idle.
            bool isMoving = isActiveAndEnabled && Time.time - lastMovementTime <= animatorMovingGraceTime;
            if (targetAnimator.GetBool("IsMoving") != isMoving)
                targetAnimator.SetBool("IsMoving", isMoving);
        }
    }

    private void Start()
    {
        if (GetComponentInChildren<PlayerController>(true) != null ||
            GetComponentInParent<PlayerController>() != null)
        {
            Debug.LogError("TargetMovement must not be attached inside the player hierarchy.", this);
            enabled = false;
            return;
        }
        Target target = GetComponentInParent<Target>();
        if (target != null) target.ConfigureNonPhysicalColliders();
        spawnLocalPosition = transform.localPosition;
        spawnWorldPosition = transform.position;
        RandomizeMovement();
        circleAngle = phaseOffset;
        initialized = true;
        BeginMovePhase();
        UpdateMovementAnimation();
    }

    private void Update()
    {
        Vector3 previousPosition = transform.position;
        bool continuousCircle = movementType == MovementType.Circular && !pauseCircularMovement;
        if (!continuousCircle && Time.time >= nextDecisionTime)
        {
            if (pausing) BeginMovePhase();
            else
            {
                pausing = true;
                nextDecisionTime = Time.time + RandomDuration(minPauseDuration, maxPauseDuration);
            }
        }
        if ((!pausing || continuousCircle) && movementSpeed > 0f && movementDistance > 0f)
        {
            if (movementType == MovementType.Circular)
            {
                circleAngle += Time.deltaTime * movementSpeed * speedMultiplier * movementDirection;
                MoveCircular(circleAngle);
            }
            else MovePhase();
        }

        Vector3 displacement = transform.position - previousPosition;
        actuallyMoving = displacement.sqrMagnitude > 0.00000001f;
        if (actuallyMoving) lastMovementTime = Time.time;
        // Face the real horizontal displacement, not a fixed animation direction.
        displacement.y = 0f;
        if (targetAnimator != null && displacement.sqrMagnitude > 0.000001f)
        {
            Quaternion facing = Quaternion.LookRotation(displacement, Vector3.up);
            transform.rotation = Quaternion.RotateTowards(transform.rotation, facing,
                Mathf.Max(0f, turnSpeed) * Time.deltaTime);
        }
        UpdateMovementAnimation();
    }

    private void BeginMovePhase()
    {
        pausing = false;
        phaseStartTime = Time.time;
        phaseDuration = RandomDuration(minMoveDuration, maxMoveDuration);
        // Keep a phase's speed fixed; only randomize it between phases.
        speedMultiplier = randomizeSpeed ? Random.Range(Mathf.Max(0.01f, minSpeedMultiplier),
            Mathf.Max(0.01f, minSpeedMultiplier, maxSpeedMultiplier)) : 1f;
        phaseStartPosition = UsesRoaming ? transform.position : transform.localPosition;
        float radius = Mathf.Max(0f, movementDistance);
        if (UsesRoaming)
        {
            phaseEndPosition = spawnWorldPosition;
            for (int attempt = 0; attempt < 12; attempt++)
            {
                Vector2 point = Random.insideUnitCircle * radius;
                Vector3 candidate = spawnWorldPosition + new Vector3(point.x, 0f, point.y);
                Vector3 travel = candidate - phaseStartPosition;
                travel.y = 0f;
                if (travel.magnitude < radius * 0.5f || !TryGroundPosition(ref candidate)) continue;
                phaseEndPosition = candidate;
                break;
            }
            phaseEndPosition.y = phaseStartPosition.y;
        }
        else
        {
            Vector3 axis = movementType == MovementType.Vertical ? Vector3.up : Vector3.right;
            float current = Vector3.Dot(phaseStartPosition - spawnLocalPosition, axis);
            float sign = Random.value < 0.5f ? -1f : 1f;
            float endpoint = sign * Random.Range(radius * 0.5f, radius);
            if (Mathf.Abs(endpoint - current) < radius * 0.5f) endpoint = -sign * radius;
            phaseEndPosition = spawnLocalPosition + axis * endpoint;
        }
        // Fit the segment to the whole duration: no early boundary stop or reversal.
        if (movementType != MovementType.Circular)
            phaseDuration = Mathf.Max(phaseDuration, Vector3.Distance(phaseStartPosition, phaseEndPosition)
                / Mathf.Max(0.01f, movementSpeed * speedMultiplier));
        nextDecisionTime = phaseStartTime + phaseDuration;
    }

    private void MovePhase()
    {
        float progress = Mathf.Clamp01((Time.time - phaseStartTime) / phaseDuration);
        Vector3 candidate = Vector3.Lerp(phaseStartPosition, phaseEndPosition, progress);
        if (UsesRoaming)
        {
            if (TryGroundPosition(ref candidate)) transform.position = candidate;
            // Blocked ground never advances the phase timer or changes direction.
        }
        else transform.localPosition = candidate;
    }

    private bool TryGroundPosition(ref Vector3 candidate)
    {
        RaycastHit[] hits = Physics.RaycastAll(candidate + Vector3.up * 3f,
            Vector3.down, 6f, groundLayers, QueryTriggerInteraction.Ignore);
        bool found = false;
        float nearest = float.PositiveInfinity;
        float height = candidate.y;
        foreach (RaycastHit hit in hits)
        {
            if (hit.normal.y < 0.5f || hit.collider.GetComponentInParent<Target>() != null ||
                hit.collider.GetComponentInParent<CharacterController>() != null) continue;
            if (Mathf.Abs(hit.point.y + groundOffset - transform.position.y) > 0.4f) continue;
            if (hit.distance >= nearest) continue;
            nearest = hit.distance;
            height = hit.point.y + groundOffset;
            found = true;
        }
        candidate.y = height;
        return found;
    }

    private static float RandomDuration(float minimum, float maximum)
    {
        minimum = Mathf.Max(0.05f, minimum);
        return Random.Range(minimum, Mathf.Max(minimum, maximum));
    }

    public void Configure(MovementType newMovementType, float newMovementSpeed, float newMovementDistance)
    {
        movementType = newMovementType;
        movementSpeed = newMovementSpeed;
        movementDistance = newMovementDistance;
        UpdateMovementAnimation();
    }

    private void RandomizeMovement()
    {
        // Direction controls left/right, up/down, or clockwise/counter-clockwise.
        movementDirection = Random.value < 0.5f ? -1f : 1f;

        // Phase offset means every target starts at a different point in its movement.
        phaseOffset = Random.Range(0f, Mathf.PI * 2f);

        if (randomizeSpeed)
        {
            speedMultiplier = Random.Range(minSpeedMultiplier, maxSpeedMultiplier);
        }
        else
        {
            speedMultiplier = 1f;
        }
    }

    private void MoveCircular(float time)
    {
        float xOffset = Mathf.Cos(time) * movementDistance;
        float yOffset = Mathf.Sin(time) * movementDistance;
        if (groundedHumanoid)
        {
            Vector3 candidate = spawnWorldPosition + new Vector3(xOffset, 0f, yOffset);
            if (TryGroundPosition(ref candidate)) transform.position = candidate;
        }
        else transform.localPosition = spawnLocalPosition + new Vector3(xOffset, yOffset, 0f);
    }
}
