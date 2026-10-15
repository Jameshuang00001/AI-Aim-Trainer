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
    public float LatestReactionTime { get; private set; }

    private float totalReactionTime;
    private readonly SessionJsonLog sessionLog = new SessionJsonLog();

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
        if (!CanRegisterStats())
        {
            return;
        }

        ShotsFired++;
        sessionLog.RegisterShot();
        UpdateAccuracy();
        NotifyStatsChanged();
    }

    public void ResetStats()
    {
        sessionLog.Begin();
        ShotsFired = 0;
        Hits = 0;
        Misses = 0;
        LatestReactionTime = 0f;
        totalReactionTime = 0f;
        AccuracyPercentage = 0f;
        AverageReactionTime = 0f;
        NotifyStatsChanged();
    }

    public void RegisterHit(float reactionTime, string targetId = null)
    {
        if (!CanRegisterStats())
        {
            return;
        }

        Hits++;
        sessionLog.RegisterResult(true, targetId, reactionTime);
        LatestReactionTime = reactionTime;
        totalReactionTime += reactionTime;
        AverageReactionTime = totalReactionTime / Hits;

        UpdateAccuracy();
        NotifyStatsChanged();
        NotifyHitFeedback(reactionTime);
        LogStats();
    }

    public void RegisterMiss(string targetId = null)
    {
        if (!CanRegisterStats())
        {
            return;
        }

        Misses++;
        sessionLog.RegisterResult(false, targetId);
        UpdateAccuracy();
        NotifyStatsChanged();
        if (uiManager != null) uiManager.ShowMissFeedback();
        LogStats();
    }

    public void SetUIManager(UIManager newUIManager)
    {
        uiManager = newUIManager;
        NotifyStatsChanged();
    }

    public string ExportSessionJson()
    {
        return sessionLog.Export(this);
    }

    private void UpdateAccuracy()
    {
        AccuracyPercentage = ShotsFired > 0 ? (float)Hits / ShotsFired * 100f : 0f;
    }

    private bool CanRegisterStats()
    {
        // Menu and completed sessions must not change the score.
        return SessionManager.Instance != null && SessionManager.Instance.IsSessionActive && !SessionManager.Instance.IsPaused;
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
