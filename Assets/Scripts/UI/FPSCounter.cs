using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Attach to a UI Text or assign a Text reference in the Inspector.
/// </summary>
public class FPSCounter : MonoBehaviour
{
    [SerializeField] private Text fpsText;
    [SerializeField, Min(0.01f)] private float updateInterval = 0.25f;
    [SerializeField] private bool showMilliseconds = false;

    private float elapsedTime;
    private int frameCount;

    private void Awake()
    {
        if (fpsText == null) fpsText = GetComponent<Text>();
    }

    private void OnEnable()
    {
        elapsedTime = 0f;
        frameCount = 0;
    }

    private void Update()
    {
        if (fpsText == null) return;

        // Unscaled time keeps the counter working even when gameplay is paused.
        elapsedTime += Time.unscaledDeltaTime;
        frameCount++;
        if (elapsedTime < Mathf.Max(0.01f, updateInterval)) return;

        float fps = frameCount / elapsedTime;
        float milliseconds = elapsedTime / frameCount * 1000f;
        fpsText.text = showMilliseconds
            ? $"FPS: {Mathf.RoundToInt(fps)} | {milliseconds:F1} ms"
            : $"FPS: {Mathf.RoundToInt(fps)}";

        elapsedTime = 0f;
        frameCount = 0;
    }
}
