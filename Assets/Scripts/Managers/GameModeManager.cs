using UnityEngine;

public enum AimTrainingMode
{
    StaticTargets,
    MovingTargets,
    FlickTargets,
    ReactionTargets
}

/// <summary>Starts in Static Targets; settings can change the mode during gameplay.</summary>
public class GameModeManager : MonoBehaviour
{
    public static GameModeManager Instance { get; private set; }

    [SerializeField] private AimTrainingMode currentMode = AimTrainingMode.StaticTargets;
    public AimTrainingMode CurrentMode => currentMode;
    public bool HasGameStarted { get; private set; }

    public void SetStaticTargetsMode() => SetMode(AimTrainingMode.StaticTargets);
    public void SetMovingTargetsMode() => SetMode(AimTrainingMode.MovingTargets);
    public void SetFlickTargetsMode() => SetMode(AimTrainingMode.FlickTargets);
    public void SetReactionTargetsMode() => SetMode(AimTrainingMode.ReactionTargets);

    public void SetMode(AimTrainingMode mode)
    {
        if (!System.Enum.IsDefined(typeof(AimTrainingMode), mode) || currentMode == mode) return;
        currentMode = mode;
        if (SessionManager.Instance != null && SessionManager.Instance.IsSessionActive)
            foreach (TargetSpawner spawner in FindObjectsOfType<TargetSpawner>())
                spawner.ResetForModeChange();
        UIManager ui = FindObjectOfType<UIManager>();
        if (ui != null) ui.RefreshMode();
    }

    public void StartGame()
    {
        if (HasGameStarted) return;
        if (SessionManager.Instance == null)
        {
            Debug.LogWarning("Add a SessionManager to the scene before starting.");
            return;
        }

        // Starting never depends on a previous menu selection or Inspector override.
        SetMode(AimTrainingMode.StaticTargets);
        HasGameStarted = true;
        SessionManager.Instance.BeginSession();
        UIManager ui = FindObjectOfType<UIManager>();
        if (ui != null) ui.HideStartMenu();
        Cursor.lockState = CursorLockMode.Locked;
        Cursor.visible = false;
    }

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
        currentMode = AimTrainingMode.StaticTargets;
    }

    private void OnDestroy()
    {
        if (Instance == this) Instance = null;
    }
}
