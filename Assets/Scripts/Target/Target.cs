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

    [Header("Target Colors")]
    [SerializeField] private Color normalColor = Color.white;
    [SerializeField] private Color inactiveColor = Color.gray;
    [SerializeField] private Color activeColor = Color.red;

    private Coroutine activationRoutine;

    private bool wasHit;

    private void OnEnable()
    {
        SpawnTime = Time.time;
        wasHit = false;
        IsHittable = true;
        SetColor(normalColor);
    }

    public void Configure(AimTrainingMode mode, float reactionDelay)
    {
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
        if (SessionManager.Instance != null && !SessionManager.Instance.IsSessionActive) return;
        if (wasHit)
        {
            return;
        }

        if (!IsHittable)
        {
            // Early reaction shots count as misses; the target remains until a valid hit.
            if (ScoreManager.Instance != null) ScoreManager.Instance.RegisterMiss();
            return;
        }

        wasHit = true;
        IsHittable = false;
        float reactionTime = Time.time - SpawnTime;

        if (ScoreManager.Instance != null)
        {
            ScoreManager.Instance.RegisterHit(reactionTime);
        }

        HitRegistered?.Invoke(this);
        gameObject.SetActive(false);
        Destroy(gameObject);
    }
}
