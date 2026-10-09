using UnityEngine;

/// <summary>
/// Attach to a scene GameObject to apply a simple frame rate limit.
/// </summary>
public class PerformanceSettings : MonoBehaviour
{
    [SerializeField] private int targetFrameRate = 60;
    public int TargetFrameRate => targetFrameRate;

    private void Awake()
    {
        SetFrameRate(targetFrameRate);
    }

    public void SetFrameRate(int value)
    {
        targetFrameRate = value <= 0 ? -1 : value;
        // Disable VSync so the requested frame rate controls the limit.
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = targetFrameRate;
    }
}
