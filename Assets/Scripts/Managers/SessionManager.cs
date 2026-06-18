using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Controls a timed aim training session.
/// Place one SessionManager in the scene. The session starts automatically on Play.
/// </summary>
public class SessionManager : MonoBehaviour
{
    public static SessionManager Instance { get; private set; }

    [Header("Session")]
    [SerializeField] private float sessionDuration = 60f;

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

        if (uiManager == null)
        {
            uiManager = FindObjectOfType<UIManager>();
        }
    }

    private void Start()
    {
        StartSession();
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

        RemainingTime -= Time.deltaTime;

        if (RemainingTime <= 0f)
        {
            EndSession();
        }
    }

    public void StartSession()
    {
        RemainingTime = sessionDuration;
        IsSessionActive = true;
        IsSessionComplete = false;

        Debug.Log($"Session started. Duration: {sessionDuration:F0} seconds.");
    }

    public void EndSession()
    {
        if (IsSessionComplete)
        {
            return;
        }

        RemainingTime = 0f;
        IsSessionActive = false;
        IsSessionComplete = true;

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
