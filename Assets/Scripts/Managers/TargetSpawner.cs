using System.Collections.Generic;
using UnityEngine;

public enum SpawnAreaMode
{
    AroundPlayer,
    ForwardRectangle
}

/// <summary>
/// Spawns targets at random positions in front of the player.
/// If no prefab is assigned, it creates a simple primitive target.
/// </summary>
public class TargetSpawner : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private Transform playerTransform;
    [SerializeField] private GameObject targetPrefab;

    [Header("Spawn Area")]
    [SerializeField] private SpawnAreaMode spawnAreaMode = SpawnAreaMode.ForwardRectangle;
    [Tooltip("Optional world-aligned rectangle center. Without it, use player-relative forward distances.")]
    [SerializeField] private Transform spawnAreaCenter;
    [SerializeField, Min(0f)] private float spawnAreaWidth = 12f;
    [SerializeField, Min(0f)] private float spawnAreaDepth = 14f;
    [SerializeField, Min(0f)] private float forwardAreaMinZ = 8f;
    [SerializeField, Min(0f)] private float forwardAreaMaxZ = 22f;
    [SerializeField] private bool facePlayerOnSpawn = true;
    [Tooltip("Assign the platform root to exclude its collider footprint. Auto-finds an object named ShootingPlatform.")]
    [SerializeField] private Transform shootingPlatform;
    private Collider[] platformColliders = new Collider[0];

    [Header("Spawn Settings")]
    [SerializeField] private float spawnInterval = 1.5f;
    [SerializeField] private float spawnRadius = 5f;
    [SerializeField] private float minDistance = 8f;
    [SerializeField] private float maxDistance = 20f;
    [SerializeField] private int maxActiveTargets = 5;

    [Header("Grounded Prefabs")]
    [Tooltip("Use for humanoid prefabs whose root is at their feet. Primitive fallback targets still float.")]
    [SerializeField] private bool spawnTargetsOnGround = true;
    [SerializeField, Min(1f)] private float groundRaycastHeight = 10f;
    [SerializeField] private float groundOffset = 0f;

    [Header("Ground Clearance")]
    [SerializeField, Min(0f)] private float minSpawnHeight = 1f;
    [SerializeField, Min(0f)] private float maxSpawnHeight = 4f;
    [SerializeField] private LayerMask groundLayers = ~0;
    [SerializeField, Min(1f)] private float groundRayHeight = 20f;
    [SerializeField, Min(1f)] private float groundRayDistance = 100f;
    [SerializeField, Min(1)] private int spawnAttempts = 10;

    [Header("Moving Targets")]
    [SerializeField] private TargetMovement.MovementType defaultMovementType = TargetMovement.MovementType.Horizontal;
    [SerializeField] private float defaultMovementSpeed = 2f;
    [SerializeField] private float defaultMovementDistance = 2f;

    [Header("Mode Settings")]
    [SerializeField, Min(0f)] private float flickSpawnDelay = 0.1f;
    [SerializeField, Min(0f)] private float minReactionDelay = 0.5f;
    [SerializeField, Min(0f)] private float maxReactionDelay = 2f;

    private AimTrainingMode CurrentMode => GameModeManager.Instance != null
        ? GameModeManager.Instance.CurrentMode : AimTrainingMode.StaticTargets;

    private readonly List<Target> activeTargets = new List<Target>();
    private float nextSpawnTime;

    private void Awake()
    {
        if (playerTransform == null && Camera.main != null)
        {
            playerTransform = Camera.main.transform;
        }
        if (shootingPlatform == null)
        {
            GameObject platform = GameObject.Find("ShootingPlatform");
            if (platform != null) shootingPlatform = platform.transform;
        }
        if (shootingPlatform != null)
            platformColliders = shootingPlatform.GetComponentsInChildren<Collider>(true);
    }

    private void Update()
    {
        RemoveDestroyedTargets();

        if (SessionManager.Instance == null || !SessionManager.Instance.IsSessionActive || SessionManager.Instance.IsPaused)
        {
            return;
        }

        int targetLimit = CurrentMode == AimTrainingMode.FlickTargets ? 1 : maxActiveTargets;
        if (Time.time >= nextSpawnTime && activeTargets.Count < targetLimit)
        {
            SpawnTarget();
            nextSpawnTime = Time.time + spawnInterval;
        }
    }

    private void SpawnTarget()
    {
        if (SessionManager.Instance == null || !SessionManager.Instance.IsSessionActive || SessionManager.Instance.IsPaused)
        {
            return;
        }

        if (playerTransform == null)
        {
            Debug.LogWarning("TargetSpawner needs a player transform or main camera before it can spawn targets.");
            return;
        }

        GameObject targetObject;

        if (targetPrefab != null && (targetPrefab.GetComponentInChildren<PlayerController>(true) != null ||
            targetPrefab.GetComponentInChildren<CharacterController>(true) != null))
        {
            Debug.LogError("Target prefab must not contain a player or CharacterController.", this);
            return;
        }

        if (targetPrefab != null)
        {
            targetObject = Instantiate(targetPrefab, transform.position, Quaternion.identity);
        }
        else
        {
            targetObject = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            targetObject.transform.position = transform.position;
            targetObject.transform.localScale = Vector3.one;
            targetObject.name = "Practice Target";
        }

        Target target = targetObject.GetComponent<Target>();
        if (target == null) target = targetObject.AddComponent<Target>();
        // Make fallback and prefab targets non-physical BEFORE syncing their bounds.
        target.ConfigureNonPhysicalColliders();
        Physics.SyncTransforms();
        if (!TryGetSpawnPosition(targetObject, out Vector3 spawnPosition))
        {
            targetObject.SetActive(false);
            Destroy(targetObject);
            return; // Skip this interval when all retry positions are unsafe.
        }
        targetObject.transform.position = spawnPosition;
        if (facePlayerOnSpawn)
        {
            Vector3 facing = playerTransform.position - spawnPosition;
            facing.y = 0f;
            if (facing.sqrMagnitude > 0.0001f)
                targetObject.transform.rotation = Quaternion.LookRotation(facing, Vector3.up);
        }

        AddMovementIfNeeded(targetObject);
        target.Configure(CurrentMode, Random.Range(minReactionDelay,
            Mathf.Max(minReactionDelay, maxReactionDelay)));
        target.HitRegistered += OnTargetHit;
        activeTargets.Add(target);
    }

    private void AddMovementIfNeeded(GameObject targetObject)
    {
        if (CurrentMode != AimTrainingMode.MovingTargets)
        {
            // Disable movement already present on a prefab in stationary modes.
            foreach (TargetMovement movement in targetObject.GetComponentsInChildren<TargetMovement>(true))
            {
                movement.enabled = false;
            }
            return;
        }

        TargetMovement targetMovement = targetObject.GetComponent<TargetMovement>();
        if (targetMovement == null)
        {
            targetMovement = targetObject.AddComponent<TargetMovement>();
        }

        targetMovement.Configure(defaultMovementType, defaultMovementSpeed, defaultMovementDistance);
        targetMovement.SetGroundedHumanoid(spawnTargetsOnGround && targetPrefab != null,
            groundOffset, groundLayers);
        targetMovement.enabled = true;
    }

    private void OnTargetHit(Target target)
    {
        target.HitRegistered -= OnTargetHit;
        activeTargets.Remove(target);
        if (CurrentMode == AimTrainingMode.FlickTargets)
        {
            nextSpawnTime = Time.time + flickSpawnDelay;
        }
    }

    private bool TryGetSpawnPosition(GameObject targetObject, out Vector3 spawnPosition)
    {
        spawnPosition = Vector3.zero;
        // Humanoid roots go directly on the ground; fallback spheres retain clearance.
        bool groundedPrefab = spawnTargetsOnGround && targetPrefab != null;
        Bounds bounds = new Bounds(targetObject.transform.position, Vector3.zero);
        if (!groundedPrefab)
        {
            // Only floating targets use visual/collider bounds and min/max spawn height.
            foreach (Renderer targetRenderer in targetObject.GetComponentsInChildren<Renderer>())
                bounds.Encapsulate(targetRenderer.bounds);
            foreach (Collider targetCollider in targetObject.GetComponentsInChildren<Collider>())
                bounds.Encapsulate(targetCollider.bounds);
        }
        Vector3 centerOffset = bounds.center - targetObject.transform.position;
        float bottomOffset = targetObject.transform.position.y - bounds.min.y;

        // Flatten camera forward so looking down cannot push targets underground.
        Vector3 forward = Vector3.ProjectOnPlane(playerTransform.forward, Vector3.up).normalized;
        if (forward.sqrMagnitude < 0.01f)
            forward = Vector3.ProjectOnPlane(playerTransform.right, Vector3.up).normalized;
        Vector3 right = Vector3.Cross(Vector3.up, forward);

        // Reserve room below the spawn point for the entire vertical movement arc.
        float verticalTravel = CurrentMode == AimTrainingMode.MovingTargets &&
            defaultMovementType != TargetMovement.MovementType.Horizontal
            ? Mathf.Abs(defaultMovementDistance) : 0f;
        float minimumHeight = Mathf.Max(minSpawnHeight, bottomOffset + verticalTravel + 0.05f);
        if (!groundedPrefab && minimumHeight > maxSpawnHeight) return false;

        for (int attempt = 0; attempt < Mathf.Max(1, spawnAttempts); attempt++)
        {
            Vector3 candidate = GetRandomAreaPosition(forward, right);
            if (spawnAreaMode == SpawnAreaMode.ForwardRectangle)
            {
                Vector3 fromPlayer = candidate - playerTransform.position;
                fromPlayer.y = 0f;
                // Even a misplaced rectangle center must not spawn behind the player.
                if (Vector3.Dot(fromPlayer, forward) <= 0f || IsOverPlatform(candidate)) continue;
            }
            float rayHeight = groundedPrefab ? groundRaycastHeight : groundRayHeight;
            Vector3 rayOrigin = candidate + Vector3.up * rayHeight;
            RaycastHit[] groundHits = Physics.RaycastAll(rayOrigin, Vector3.down,
                groundRayDistance, groundLayers, QueryTriggerInteraction.Ignore);
            bool foundGround = false;
            bool hitPlatform = false;
            float groundY = float.NegativeInfinity;
            foreach (RaycastHit hit in groundHits)
            {
                // Reject the entire candidate, not just this hit: otherwise a ray
                // could select the arena floor underneath the shooting platform.
                if (spawnAreaMode == SpawnAreaMode.ForwardRectangle && IsPlatformCollider(hit.collider))
                {
                    hitPlatform = true;
                    break;
                }
                // Never treat the player or other targets as ground.
                if (hit.collider.transform.IsChildOf(targetObject.transform) ||
                    hit.collider.GetComponentInParent<Target>() != null ||
                    hit.collider.GetComponentInParent<CharacterController>() != null ||
                    hit.normal.y < 0.5f) continue;
                groundY = Mathf.Max(groundY, hit.point.y);
                foundGround = true;
            }
            if (!foundGround || hitPlatform) continue;

            if (groundedPrefab)
            {
                // Place the root, not the visual bounds. Child model offsets never
                // reject humanoid spawns or lift them to floating-target heights.
                candidate.y = groundY + groundOffset;
                spawnPosition = candidate;
                return true;
            }
            candidate.y = groundY + Random.Range(minimumHeight, maxSpawnHeight);

            // A bounds check also rejects slopes, walls, and other overlapping targets.
            bool blocked = false;
            foreach (Collider obstacle in Physics.OverlapBox(candidate + centerOffset,
                bounds.extents + Vector3.one * 0.02f, Quaternion.identity,
                Physics.AllLayers, QueryTriggerInteraction.Collide))
            {
                if (obstacle.transform.IsChildOf(targetObject.transform)) continue;
                blocked = true;
                break;
            }
            if (blocked) continue;
            spawnPosition = candidate;
            return true;
        }
        return false;
    }

    private Vector3 GetRandomAreaPosition(Vector3 forward, Vector3 right)
    {
        if (spawnAreaMode == SpawnAreaMode.AroundPlayer)
        {
            // Preserve the original forward-distance and lateral-radius placement.
            return playerTransform.position + forward * Random.Range(minDistance, maxDistance)
                + right * Random.Range(-spawnRadius, spawnRadius);
        }

        float halfWidth = Mathf.Max(0f, spawnAreaWidth) * 0.5f;
        if (spawnAreaCenter != null)
        {
            // Center defines a world X/Z rectangle; its rotation is not used.
            float halfDepth = Mathf.Max(0f, spawnAreaDepth) * 0.5f;
            Vector3 center = spawnAreaCenter.position;
            return new Vector3(center.x + Random.Range(-halfWidth, halfWidth),
                Mathf.Max(center.y, playerTransform.position.y),
                center.z + Random.Range(-halfDepth, halfDepth));
        }

        // Local Z means distance along the player's flattened forward direction.
        float minimum = Mathf.Max(0f, forwardAreaMinZ);
        float maximum = Mathf.Max(minimum, forwardAreaMaxZ);
        return playerTransform.position + right * Random.Range(-halfWidth, halfWidth)
            + forward * Random.Range(minimum, maximum);
    }

    private bool IsOverPlatform(Vector3 position)
    {
        foreach (Collider platform in platformColliders)
        {
            if (platform == null || !platform.enabled || !platform.gameObject.activeInHierarchy) continue;
            Bounds bounds = platform.bounds;
            if (position.x >= bounds.min.x && position.x <= bounds.max.x &&
                position.z >= bounds.min.z && position.z <= bounds.max.z) return true;
        }
        return false;
    }

    private bool IsPlatformCollider(Collider collider)
    {
        if (shootingPlatform != null && collider.transform.IsChildOf(shootingPlatform)) return true;
        // Also handle named platform hierarchies when the reference is unassigned.
        for (Transform parent = collider.transform; parent != null; parent = parent.parent)
            if (parent.name == "ShootingPlatform") return true;
        return false;
    }

    private void RemoveDestroyedTargets()
    {
        for (int i = activeTargets.Count - 1; i >= 0; i--)
        {
            if (activeTargets[i] == null)
            {
                activeTargets.RemoveAt(i);
            }
        }
    }

    public void DestroyActiveTargets()
    {
        for (int i = activeTargets.Count - 1; i >= 0; i--)
        {
            if (activeTargets[i] != null)
            {
                activeTargets[i].HitRegistered -= OnTargetHit;
                Destroy(activeTargets[i].gameObject);
            }
        }

        activeTargets.Clear();
    }

    public void ResetForModeChange()
    {
        DestroyActiveTargets();
        nextSpawnTime = Time.time;
    }
}
