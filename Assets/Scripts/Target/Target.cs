using UnityEngine;

/// <summary>
/// Aim trainer target. Records when it appeared so hits can report reaction time.
/// </summary>
public class Target : MonoBehaviour
{
    public float SpawnTime { get; private set; }

    private bool wasHit;

    private void OnEnable()
    {
        SpawnTime = Time.time;
        wasHit = false;
    }

    public void Hit()
    {
        if (wasHit)
        {
            return;
        }

        wasHit = true;
        float reactionTime = Time.time - SpawnTime;

        if (ScoreManager.Instance != null)
        {
            ScoreManager.Instance.RegisterHit(reactionTime);
        }

        Destroy(gameObject);
    }
}
