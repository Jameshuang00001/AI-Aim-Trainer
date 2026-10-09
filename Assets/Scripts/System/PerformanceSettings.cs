using UnityEngine;

/// <summary>
/// Attach to a scene GameObject to apply a simple frame rate limit.
/// </summary>
public class PerformanceSettings : MonoBehaviour
{
    [SerializeField] private int targetFrameRate = 60;

    private void Awake()
    {
        // Disable VSync so the requested frame rate controls the limit.
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = targetFrameRate;
    }
}
