using UnityEngine;

/// <summary>
/// Controls a timed aim training session.
/// Place one SessionManager in the scene. GameModeManager starts it from the menu.
/// </summary>
[DefaultExecutionOrder(-1000)]
public class SessionManager : MonoBehaviour
{
    public static SessionManager Instance { get; private set; }

    [Header("Session")]
    [SerializeField] private bool unlimitedTime = true;
    [SerializeField, Min(1f)] private float selectedTimeLimit = 60f;
    public bool UnlimitedTime => unlimitedTime;
    public float SelectedTimeLimit => selectedTimeLimit;

    [Header("UI")]
    [SerializeField] private UIManager uiManager;

    public float RemainingTime { get; private set; }
    public bool IsSessionActive { get; private set; }
    public bool IsSessionComplete { get; private set; }
    public bool IsPaused { get; private set; }
    public bool IsSummaryOpen { get; private set; }
    private float resumeTimeScale = 1f;
    private int resumedFrame = -1;
    public bool CanShoot => IsSessionActive && !IsPaused && Time.frameCount != resumedFrame;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
        if (FindObjectOfType<SettingsMenuManager>(true) == null)
            gameObject.AddComponent<SettingsMenuManager>();
        RemainingTime = unlimitedTime ? 0f : Mathf.Max(1f, selectedTimeLimit);

        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }
    }

    private void Update()
    {
        if (!IsSessionActive)
        {
            return;
        }

        if (IsPaused || unlimitedTime) return;

        RemainingTime -= Time.deltaTime;

        if (RemainingTime <= 0f)
        {
            EndSession();
        }
    }

    public void StartSession()
    {
        BeginSession();
    }

    public void BeginSession()
    {
        if (IsSessionActive) return;
        DestroyActiveTargets();
        if (ScoreManager.Instance != null) ScoreManager.Instance.ResetStats();
        RemainingTime = unlimitedTime ? 0f : Mathf.Max(1f, selectedTimeLimit);
        IsSessionActive = true;
        IsSessionComplete = false;
        IsSummaryOpen = false;

        if (uiManager != null) uiManager.HideSummaryPanel();

        Debug.Log(unlimitedTime ? "Session started. Unlimited time."
            : $"Session started. Duration: {selectedTimeLimit:F0} seconds.");
    }

    // Switching time limits resets only the timer, not targets, score, or pause state.
    public void SetTimeLimit(bool unlimited, float seconds = 60f)
    {
        unlimitedTime = unlimited;
        selectedTimeLimit = Mathf.Max(1f, seconds);
        RemainingTime = unlimitedTime ? 0f : selectedTimeLimit;
    }

    public void ResetSessionData(bool clearTargets = true)
    {
        if (!IsSessionActive) return;
        // Keep the current settings, pause state, and open menu unchanged.
        RemainingTime = unlimitedTime ? 0f : Mathf.Max(1f, selectedTimeLimit);
        IsSessionComplete = false;
        IsSummaryOpen = false;
        if (clearTargets)
            foreach (TargetSpawner spawner in FindObjectsOfType<TargetSpawner>())
                spawner.ResetForModeChange();
        foreach (Gun gun in FindObjectsOfType<Gun>()) gun.ResetSessionState();
        if (ScoreManager.Instance != null) ScoreManager.Instance.ResetStats();
        if (uiManager == null) uiManager = FindObjectOfType<UIManager>();
        if (uiManager != null)
        {
            uiManager.HideSummaryPanel();
            uiManager.RefreshMode();
            uiManager.RefreshSession();
            if (ScoreManager.Instance != null) uiManager.RefreshStats(ScoreManager.Instance);
        }
    }

    public void EndSession()
    {
        if (!IsSessionActive)
        {
            return;
        }

        SettingsMenuManager settings = FindObjectOfType<SettingsMenuManager>(true);
        if (settings != null) settings.HidePanel();
        // Expired timers become unlimited; manual viewing preserves a running timer.
        if (!unlimitedTime && RemainingTime <= 0f) SetTimeLimit(true, selectedTimeLimit);
        IsSummaryOpen = true;
        CursorStateManager.GetOrCreate().EnterMenuCursorMode();
        ShowSessionCompleteUI();
        LogFinalStats();
    }

    public void CloseSummary()
    {
        if (!IsSummaryOpen) return;
        IsSummaryOpen = false;
        if (uiManager != null) uiManager.HideSummaryPanel();
        CursorStateManager.GetOrCreate().EnterGameplayCursorMode();
        Debug.Log("Closed SummaryPanel and relocked cursor");
    }

    public void SetPaused(bool paused)
    {
        if (paused == IsPaused || (paused && !IsSessionActive))
            return;
        if (paused) resumeTimeScale = Time.timeScale;
        IsPaused = paused;
        if (!paused)
        {
            resumedFrame = Time.frameCount;
            Input.ResetInputAxes();
        }
        // Scaled timers, target movement, and animations freeze together.
        Time.timeScale = paused ? 0f : resumeTimeScale;
    }

    private void OnDestroy()
    {
        if (Instance != this) return;
        if (IsPaused) Time.timeScale = resumeTimeScale;
        Instance = null;
    }

    private void DestroyActiveTargets()
    {
        TargetSpawner[] targetSpawners = FindObjectsOfType<TargetSpawner>();

        for (int i = 0; i < targetSpawners.Length; i++)
        {
            targetSpawners[i].DestroyActiveTargets();
        }
    }

    private void ShowSessionCompleteUI()
    {
        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }

        if (uiManager != null)
        {
            uiManager.ShowSessionComplete();
        }
    }

    private void LogFinalStats()
    {
        ScoreManager scoreManager = ScoreManager.Instance;

        if (scoreManager == null)
        {
            Debug.Log("Session complete. No ScoreManager was found for final stats.");
            return;
        }

        Debug.Log(
            $"Session complete! Final Stats - Shots: {scoreManager.ShotsFired} | " +
            $"Hits: {scoreManager.Hits} | Misses: {scoreManager.Misses} | " +
            $"Accuracy: {scoreManager.AccuracyPercentage:F1}% | " +
            $"Avg Reaction: {scoreManager.AverageReactionTime:F3}s"
        );
    }
}
