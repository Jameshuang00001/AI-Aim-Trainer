using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Aim trainer target. Records when it appeared so hits can report reaction time.
/// </summary>
public class Target : MonoBehaviour
{
    public float SpawnTime { get; private set; }
    public bool IsHittable { get; private set; }
    public event Action<Target> HitRegistered;

    [Header("Humanoid Animation")]
    [SerializeField] private Animator targetAnimator;
    [SerializeField, Min(0f)] private float deathDestroyDelay = 1.2f;
    [SerializeField] private bool settleDeathOnGround = true;
    [SerializeField] private LayerMask deathGroundLayers = ~0;
    [SerializeField, Min(0f)] private float deathSettleSpeed = 8f;

    private SkinnedMeshRenderer[] deathRenderers;
    private Mesh deathMesh;
    private readonly List<Vector3> deathVertices = new List<Vector3>();
    private float deathStartTime;
    private float deathGroundY;
    private bool hasDeathGround;

    [Header("Target Colors")]
    [SerializeField] private Color normalColor = Color.white;
    [SerializeField] private Color inactiveColor = Color.gray;
    [SerializeField] private Color activeColor = Color.red;

    [Header("Hit Feedback")]
    [SerializeField] private Color hitColor = Color.green;
    [SerializeField, Min(0f)] private float hitFeedbackDuration = 0.12f;
    [SerializeField, Min(1f)] private float hitScaleMultiplier = 1.2f;

    private Coroutine activationRoutine;

    private bool hasBeenHit;

    private void Awake()
    {
        // Reject an accidentally attached Target on the player or a parent of it.
        if (GetComponentInChildren<PlayerController>(true) != null ||
            GetComponentInParent<PlayerController>() != null)
        {
            Debug.LogError("Target must be on a separate target object, outside the player hierarchy.", this);
            enabled = false;
            return;
        }
        ConfigureNonPhysicalColliders();
        if (targetAnimator == null) targetAnimator = GetComponentInChildren<Animator>();
        if (targetAnimator != null)
        {
            // TargetMovement owns position; animations must never move the root.
            targetAnimator.applyRootMotion = false;
            targetAnimator.SetBool("IsMoving", false);
            deathRenderers = targetAnimator.GetComponentsInChildren<SkinnedMeshRenderer>();
        }
    }

    public void ConfigureNonPhysicalColliders()
    {
        if (!enabled) return;
        // Aim targets are raycast surfaces, never obstacles that push the player.
        foreach (Collider targetCollider in GetComponentsInChildren<Collider>(true))
        {
            MeshCollider mesh = targetCollider as MeshCollider;
            if (mesh != null && !mesh.convex) mesh.convex = true;
            targetCollider.isTrigger = true;
        }
        foreach (Rigidbody body in GetComponentsInChildren<Rigidbody>(true))
        {
            body.isKinematic = true;
            body.useGravity = false;
        }
    }

    private void OnEnable()
    {
        if (!enabled) return;
        SpawnTime = Time.time;
        hasBeenHit = false;
        IsHittable = true;
        SetColor(normalColor);
    }

    public void Configure(AimTrainingMode mode, float reactionDelay)
    {
        if (!enabled) return;
        if (activationRoutine != null) StopCoroutine(activationRoutine);
        activationRoutine = null;
        SpawnTime = Time.time;
        IsHittable = mode != AimTrainingMode.ReactionTargets;
        SetColor(IsHittable ? normalColor : inactiveColor);
        if (!IsHittable)
        {
            activationRoutine = StartCoroutine(ActivateAfterDelay(reactionDelay));
        }
    }

    private IEnumerator ActivateAfterDelay(float delay)
    {
        yield return new WaitForSeconds(Mathf.Max(0f, delay));
        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive) yield break;
        IsHittable = true;
        // Measure reaction time from the red signal, excluding the waiting period.
        SpawnTime = Time.time;
        SetColor(activeColor);
        activationRoutine = null;
    }

    private void SetColor(Color color)
    {
        // Property blocks tint primitives without creating or changing shared materials.
        foreach (Renderer targetRenderer in GetComponentsInChildren<Renderer>())
        {
            MaterialPropertyBlock properties = new MaterialPropertyBlock();
            targetRenderer.GetPropertyBlock(properties);
            properties.SetColor("_Color", color);
            targetRenderer.SetPropertyBlock(properties);
        }
    }

    public void Hit()
    {
        if (!enabled) return;
        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive) return;
        if (hasBeenHit)
        {
            return;
        }

        if (!IsHittable)
        {
            // Early reaction shots count as misses; the target remains until a valid hit.
            if (ScoreManager.Instance != null) ScoreManager.Instance.RegisterMiss();
            return;
        }

        hasBeenHit = true;
        IsHittable = false;
        // Disable collision and movement before score callbacks or visual changes.
        foreach (Collider targetCollider in GetComponentsInChildren<Collider>(true))
            targetCollider.enabled = false;
        foreach (TargetMovement movement in GetComponentsInChildren<TargetMovement>(true))
            movement.enabled = false;
        float reactionTime = Time.time - SpawnTime;

        if (ScoreManager.Instance != null)
        {
            ScoreManager.Instance.RegisterHit(reactionTime);
        }

        if (targetAnimator != null)
        {
            deathStartTime = Time.time;
            FindDeathGround();
            targetAnimator.SetBool("IsMoving", false);
            targetAnimator.SetTrigger("Death");
            StartCoroutine(DestroyAfterDeath());
        }
        else
        {
            // Primitive targets retain their short color/scale pulse.
            StartCoroutine(PlayHitFeedback());
        }
    }

    private void FindDeathGround()
    {
        hasDeathGround = false;
        float closestDistance = float.PositiveInfinity;
        foreach (RaycastHit hit in Physics.RaycastAll(transform.position + Vector3.up * 5f,
            Vector3.down, 100f, deathGroundLayers, QueryTriggerInteraction.Ignore))
        {
            if (hit.normal.y < 0.5f || hit.collider.GetComponentInParent<Target>() != null ||
                hit.collider.GetComponentInParent<CharacterController>() != null) continue;
            if (hit.distance >= closestDistance) continue;
            closestDistance = hit.distance;
            deathGroundY = hit.point.y;
            hasDeathGround = true;
        }
    }

    private void LateUpdate()
    {
        if (!hasBeenHit || targetAnimator == null || !settleDeathOnGround || !hasDeathGround ||
            Time.time - deathStartTime < 0.15f) return;
        if (deathMesh == null) deathMesh = new Mesh();
        float lowestY = float.PositiveInfinity;
        // Skin bounds can stay at the standing pose. Measure the actual animated mesh
        // during the short death period so a lying body cannot remain suspended.
        foreach (SkinnedMeshRenderer body in deathRenderers)
        {
            if (!body.enabled || body.sharedMesh == null) continue;
            body.BakeMesh(deathMesh);
            deathMesh.GetVertices(deathVertices);
            foreach (Vector3 vertex in deathVertices)
                lowestY = Mathf.Min(lowestY, body.transform.TransformPoint(vertex).y);
        }
        if (float.IsPositiveInfinity(lowestY)) return;
        Vector3 position = transform.position;
        float groundedY = position.y + deathGroundY + 0.02f - lowestY;
        position.y = Mathf.MoveTowards(position.y, groundedY, deathSettleSpeed * Time.deltaTime);
        transform.position = position; // Only this collider-disabled target moves.
    }

    private void OnDestroy()
    {
        if (deathMesh != null) Destroy(deathMesh);
    }

    private IEnumerator DestroyAfterDeath()
    {
        // Keep the target tracked until its animation finishes, so session cleanup
        // can still remove it and flick mode waits for this target to disappear.
        yield return new WaitForSeconds(Mathf.Max(0f, deathDestroyDelay));
        HitRegistered?.Invoke(this);
        Destroy(gameObject);
    }

    private IEnumerator PlayHitFeedback()
    {
        SetColor(hitColor);
        Vector3 originalScale = transform.localScale;
        float elapsed = 0f;
        while (elapsed < hitFeedbackDuration)
        {
            // One short pulse: grow, then shrink back to the original size.
            float pulse = Mathf.Sin(elapsed / hitFeedbackDuration * Mathf.PI);
            transform.localScale = originalScale * Mathf.Lerp(1f, hitScaleMultiplier, pulse);
            elapsed += Time.deltaTime;
            yield return null;
        }

        HitRegistered?.Invoke(this);
        Destroy(gameObject);
    }
}
