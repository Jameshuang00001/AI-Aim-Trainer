using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Spawns targets at random positions in front of the player.
/// If no prefab is assigned, it creates a simple primitive target.
/// </summary>
public class TargetSpawner : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private Transform playerTransform;
    [SerializeField] private GameObject targetPrefab;

    [Header("Spawn Settings")]
    [SerializeField] private float spawnInterval = 1.5f;
    [SerializeField] private float spawnRadius = 5f;
    [SerializeField] private float minDistance = 8f;
    [SerializeField] private float maxDistance = 20f;
    [SerializeField] private int maxActiveTargets = 5;

    [Header("Moving Targets")]
    [SerializeField] private bool enableMovingTargets;
    [SerializeField] private TargetMovement.MovementType defaultMovementType = TargetMovement.MovementType.Horizontal;
    [SerializeField] private float defaultMovementSpeed = 2f;
    [SerializeField] private float defaultMovementDistance = 2f;

    private readonly List<Target> activeTargets = new List<Target>();
    private float nextSpawnTime;

    private void Awake()
    {
        if (playerTransform == null && Camera.main != null)
        {
            playerTransform = Camera.main.transform;
        }
    }

    private void Update()
    {
        RemoveDestroyedTargets();

        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive)
        {
            return;
        }

        if (Time.time >= nextSpawnTime && activeTargets.Count < maxActiveTargets)
        {
            SpawnTarget();
            nextSpawnTime = Time.time + spawnInterval;
        }
    }

    private void SpawnTarget()
    {
        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive)
        {
            return;
        }

        if (playerTransform == null)
        {
            Debug.LogWarning("TargetSpawner needs a player transform or main camera before it can spawn targets.");
            return;
        }

        Vector3 spawnPosition = GetRandomPositionInFrontOfPlayer();
        GameObject targetObject;

        if (targetPrefab != null)
        {
            targetObject = Instantiate(targetPrefab, spawnPosition, Quaternion.identity);
        }
        else
        {
            targetObject = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            targetObject.transform.position = spawnPosition;
            targetObject.transform.localScale = Vector3.one;
            targetObject.name = "Practice Target";
        }

        Target target = targetObject.GetComponent<Target>();
        if (target == null)
        {
            target = targetObject.AddComponent<Target>();
        }

        AddMovementIfNeeded(targetObject);
        activeTargets.Add(target);
    }

    private void AddMovementIfNeeded(GameObject targetObject)
    {
        if (!enableMovingTargets)
        {
            return;
        }

        TargetMovement targetMovement = targetObject.GetComponent<TargetMovement>();
        if (targetMovement == null)
        {
            targetMovement = targetObject.AddComponent<TargetMovement>();
        }

        targetMovement.Configure(defaultMovementType, defaultMovementSpeed, defaultMovementDistance);
    }

    private Vector3 GetRandomPositionInFrontOfPlayer()
    {
        float distance = Random.Range(minDistance, maxDistance);
        Vector2 randomCirclePoint = Random.insideUnitCircle * spawnRadius;

        Vector3 forwardOffset = playerTransform.forward * distance;
        Vector3 horizontalOffset = playerTransform.right * randomCirclePoint.x;
        Vector3 verticalOffset = playerTransform.up * randomCirclePoint.y;

        return playerTransform.position + forwardOffset + horizontalOffset + verticalOffset;
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
                Destroy(activeTargets[i].gameObject);
            }
        }

        activeTargets.Clear();
    }
}
