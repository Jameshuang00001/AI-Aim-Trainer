using UnityEngine;

/// <summary>
/// Tracks aim trainer stats for the current play session.
/// Place one ScoreManager in the scene.
/// </summary>
public class ScoreManager : MonoBehaviour
{
    public static ScoreManager Instance { get; private set; }

    public int ShotsFired { get; private set; }
    public int Hits { get; private set; }
    public int Misses { get; private set; }
    public float AccuracyPercentage { get; private set; }
    public float AverageReactionTime { get; private set; }

    private float totalReactionTime;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
    }

    public void RegisterShot()
    {
        ShotsFired++;
        UpdateAccuracy();
    }

    public void RegisterHit(float reactionTime)
    {
        Hits++;
        totalReactionTime += reactionTime;
        AverageReactionTime = totalReactionTime / Hits;

        UpdateAccuracy();
        LogStats();
    }

    public void RegisterMiss()
    {
        Misses++;
        UpdateAccuracy();
        LogStats();
    }

    private void UpdateAccuracy()
    {
        AccuracyPercentage = ShotsFired > 0 ? (float)Hits / ShotsFired * 100f : 0f;
    }

    private void LogStats()
    {
        Debug.Log(
            $"Shots: {ShotsFired} | Hits: {Hits} | Misses: {Misses} | " +
            $"Accuracy: {AccuracyPercentage:F1}% | Avg Reaction: {AverageReactionTime:F3}s"
        );
    }
}
