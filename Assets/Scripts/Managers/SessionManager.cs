using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Controls a timed aim training session.
/// Place one SessionManager in the scene. GameModeManager starts it from the menu.
/// </summary>
[DefaultExecutionOrder(-1000)]
public class SessionManager : MonoBehaviour
{
    public static SessionManager Instance { get; private set; }

    [Header("Session")]
    [SerializeField, Min(0f)] private float sessionDuration = 30f;

    [Header("UI")]
    [SerializeField] private UIManager uiManager;

    public float RemainingTime { get; private set; }
    public bool IsSessionActive { get; private set; }
    public bool IsSessionComplete { get; private set; }
    public bool IsPaused { get; private set; }
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
        RemainingTime = Mathf.Max(0f, sessionDuration);

        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }
    }

    private void Update()
    {
        if (IsSessionComplete && Input.GetKeyDown(KeyCode.R))
        {
            RestartCurrentScene();
            return;
        }

        if (!IsSessionActive)
        {
            return;
        }

        if (Input.GetKeyDown(KeyCode.Escape))
        {
            SettingsMenuManager settings = FindObjectOfType<SettingsMenuManager>(true);
            if (settings != null) settings.ToggleSettings();
            return;
        }

        if (IsPaused) return;

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
        RemainingTime = Mathf.Max(0f, sessionDuration);
        IsSessionActive = true;
        IsSessionComplete = false;

        if (uiManager != null) uiManager.HideSummaryPanel();

        Debug.Log($"Session started. Duration: {sessionDuration:F0} seconds.");
    }

    public void EndSession()
    {
        if (!IsSessionActive)
        {
            return;
        }

        SetPaused(false);
        SettingsMenuManager settings = FindObjectOfType<SettingsMenuManager>(true);
        if (settings != null) settings.HidePanel();
        RemainingTime = 0f;
        IsSessionActive = false;
        IsSessionComplete = true;
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;

        DestroyActiveTargets();
        ShowSessionCompleteUI();
        LogFinalStats();
    }

    public void SetPaused(bool paused)
    {
        if (paused == IsPaused || (paused && !IsSessionActive)) return;
        if (paused) resumeTimeScale = Time.timeScale;
        IsPaused = paused;
        if (!paused)
        {
            resumedFrame = Time.frameCount;
            Input.ResetInputAxes();
        }
        // Scaled timers, target movement, and animations freeze together.
        Time.timeScale = paused ? 0f : resumeTimeScale;
        Cursor.lockState = paused ? CursorLockMode.None : CursorLockMode.Locked;
        Cursor.visible = paused;
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

    private void RestartCurrentScene()
    {
        Scene currentScene = SceneManager.GetActiveScene();
        SceneManager.LoadScene(currentScene.buildIndex);
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
