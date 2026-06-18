using System.Collections;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Displays aim trainer stats and simple visual feedback.
///
/// Scene setup:
/// 1. Create a Canvas: GameObject > UI > Canvas.
/// 2. On the Canvas, add UI Text objects for Shots, Hits, Misses, Accuracy, and Average Reaction Time.
/// 3. Add this UIManager script to the Canvas or to an empty "UIManager" GameObject.
/// 4. Drag each Text object into the matching fields in the Inspector.
/// 5. For a crosshair, create either:
///    - UI > Text with "+" centered on the screen, then assign it to Crosshair Text, or
///    - UI > Image centered on the screen, then assign it to Crosshair Image.
/// 6. Optional: create a small centered Text such as "HIT" and assign it to Hit Feedback Text.
///
/// This uses UnityEngine.UI.Text for Unity 2022.3 compatibility and does not require TextMeshPro.
/// </summary>
public class UIManager : MonoBehaviour
{
    [Header("Stats Text")]
    [SerializeField] private Text shotsText;
    [SerializeField] private Text hitsText;
    [SerializeField] private Text missesText;
    [SerializeField] private Text accuracyText;
    [SerializeField] private Text averageReactionTimeText;

    [Header("Crosshair")]
    [SerializeField] private Text crosshairText;
    [SerializeField] private Image crosshairImage;

    [Header("Hit Feedback")]
    [SerializeField] private Text hitFeedbackText;
    [SerializeField] private float hitFeedbackDuration = 0.15f;

    private Coroutine hitFeedbackRoutine;

    private void Start()
    {
        CreateDefaultCrosshairIfNeeded();
        HideHitFeedback();

        if (ScoreManager.Instance != null)
        {
            ScoreManager.Instance.SetUIManager(this);
            RefreshStats(ScoreManager.Instance);
        }
    }

    public void RefreshStats(ScoreManager scoreManager)
    {
        if (scoreManager == null)
        {
            return;
        }

        SetText(shotsText, $"Shots: {scoreManager.ShotsFired}");
        SetText(hitsText, $"Hits: {scoreManager.Hits}");
        SetText(missesText, $"Misses: {scoreManager.Misses}");
        SetText(accuracyText, $"Accuracy: {scoreManager.AccuracyPercentage:F1}%");
        SetText(averageReactionTimeText, $"Avg Reaction: {scoreManager.AverageReactionTime:F3}s");
    }

    public void ShowHitFeedback(float reactionTime)
    {
        Debug.Log($"Hit feedback triggered. Reaction time: {reactionTime:F3}s");

        if (hitFeedbackText == null)
        {
            return;
        }

        if (hitFeedbackRoutine != null)
        {
            StopCoroutine(hitFeedbackRoutine);
        }

        hitFeedbackRoutine = StartCoroutine(ShowHitFeedbackRoutine(reactionTime));
    }

    private IEnumerator ShowHitFeedbackRoutine(float reactionTime)
    {
        hitFeedbackText.text = $"HIT {reactionTime:F3}s";
        hitFeedbackText.enabled = true;

        yield return new WaitForSeconds(hitFeedbackDuration);

        HideHitFeedback();
        hitFeedbackRoutine = null;
    }

    private void HideHitFeedback()
    {
        if (hitFeedbackText != null)
        {
            hitFeedbackText.enabled = false;
        }
    }

    private void SetText(Text textComponent, string value)
    {
        if (textComponent != null)
        {
            textComponent.text = value;
        }
    }

    private void CreateDefaultCrosshairIfNeeded()
    {
        if (crosshairText != null)
        {
            if (string.IsNullOrWhiteSpace(crosshairText.text))
            {
                crosshairText.text = "+";
            }

            crosshairText.alignment = TextAnchor.MiddleCenter;
            crosshairText.enabled = true;
            return;
        }

        if (crosshairImage != null)
        {
            crosshairImage.enabled = true;
            return;
        }

        Canvas parentCanvas = GetComponentInParent<Canvas>();
        if (parentCanvas == null)
        {
            return;
        }

        GameObject crosshairObject = new GameObject("Default Crosshair", typeof(RectTransform), typeof(Text));
        crosshairObject.transform.SetParent(parentCanvas.transform, false);

        RectTransform rectTransform = crosshairObject.GetComponent<RectTransform>();
        rectTransform.anchorMin = new Vector2(0.5f, 0.5f);
        rectTransform.anchorMax = new Vector2(0.5f, 0.5f);
        rectTransform.anchoredPosition = Vector2.zero;
        rectTransform.sizeDelta = new Vector2(32f, 32f);

        crosshairText = crosshairObject.GetComponent<Text>();
        crosshairText.text = "+";
        crosshairText.font = Resources.GetBuiltinResource<Font>("Arial.ttf");
        crosshairText.fontSize = 24;
        crosshairText.alignment = TextAnchor.MiddleCenter;
        crosshairText.color = Color.white;
        crosshairText.raycastTarget = false;
    }
}
