using UnityEngine;

/// <summary>
/// Tracks aim trainer stats for the current play session.
/// Place one ScoreManager in the scene. You can drag the UIManager into the UI field,
/// or let the scripts find each other automatically at runtime.
/// </summary>
public class ScoreManager : MonoBehaviour
{
    public static ScoreManager Instance { get; private set; }

    [Header("UI")]
    [SerializeField] private UIManager uiManager;

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

        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }
    }

    public void RegisterShot()
    {
        ShotsFired++;
        UpdateAccuracy();
        NotifyStatsChanged();
    }

    public void RegisterHit(float reactionTime)
    {
        Hits++;
        totalReactionTime += reactionTime;
        AverageReactionTime = totalReactionTime / Hits;

        UpdateAccuracy();
        NotifyStatsChanged();
        NotifyHitFeedback(reactionTime);
        LogStats();
    }

    public void RegisterMiss()
    {
        Misses++;
        UpdateAccuracy();
        NotifyStatsChanged();
        LogStats();
    }

    public void SetUIManager(UIManager newUIManager)
    {
        uiManager = newUIManager;
        NotifyStatsChanged();
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

    private void NotifyStatsChanged()
    {
        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }

        if (uiManager != null)
        {
            uiManager.RefreshStats(this);
        }
    }

    private void NotifyHitFeedback(float reactionTime)
    {
        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }

        if (uiManager != null)
        {
            uiManager.ShowHitFeedback(reactionTime);
        }
    }
}
