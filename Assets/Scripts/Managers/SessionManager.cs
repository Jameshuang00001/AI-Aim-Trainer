using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Controls a timed aim training session.
/// Place one SessionManager in the scene. GameModeManager starts it from the menu.
/// </summary>
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

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
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

        // Escape uses the same cleanup and summary path as timer expiration.
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            EndSession();
            return;
        }

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

        RemainingTime = 0f;
        IsSessionActive = false;
        IsSessionComplete = true;
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;

        DestroyActiveTargets();
        ShowSessionCompleteUI();
        LogFinalStats();
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
