using UnityEngine;

public enum AimTrainingMode
{
    StaticTargets,
    MovingTargets,
    FlickTargets,
    ReactionTargets
}

/// <summary>Stores the menu selection and starts gameplay when Start is pressed.</summary>
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

    private void SetMode(AimTrainingMode mode)
    {
        // Keep the mode fixed during a session so existing targets stay consistent.
        if (HasGameStarted) return;
        currentMode = mode;
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
    }

    private void OnDestroy()
    {
        if (Instance == this) Instance = null;
    }
}
