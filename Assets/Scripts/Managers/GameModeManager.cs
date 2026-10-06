using UnityEngine;

public enum AimTrainingMode
{
    StaticTargets,
    MovingTargets,
    FlickTargets,
    ReactionTargets
}

/// <summary>Add one to the scene and select a training mode before pressing Play.</summary>
public class GameModeManager : MonoBehaviour
{
    public static GameModeManager Instance { get; private set; }

    [SerializeField] private AimTrainingMode currentMode = AimTrainingMode.StaticTargets;
    public AimTrainingMode CurrentMode => currentMode;

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
