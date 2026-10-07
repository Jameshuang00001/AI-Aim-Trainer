using System;
using System.Collections;
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
    [SerializeField, Min(0f)] private float deathDestroyDelay = 1.5f;

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
            // Scripts control movement, not animation root motion.
            targetAnimator.applyRootMotion = false;
            targetAnimator.SetBool("IsMoving", false);
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
        TryHit(HitZoneType.Body);
    }

    // Both zones score one normal hit for now. Return acceptance for marker feedback.
    public bool TryHit(HitZoneType zone)
    {
        if (!enabled) return false;
        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive) return false;
        if (hasBeenHit)
        {
            return false;
        }

        if (!IsHittable)
        {
            // Early reaction shots count as misses; the target remains until a valid hit.
            if (ScoreManager.Instance != null) ScoreManager.Instance.RegisterMiss();
            return false;
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
            // Let the death pose play normally without ground correction or visual locks.
            targetAnimator.applyRootMotion = false;
            targetAnimator.SetBool("IsMoving", false);
            targetAnimator.SetTrigger("Death");
            StartCoroutine(DestroyAfterDeath());
        }
        else
        {
            // Primitive targets retain their short color/scale pulse.
            StartCoroutine(PlayHitFeedback());
        }
        return true;
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
