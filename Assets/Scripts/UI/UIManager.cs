using System.Collections;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Displays aim trainer stats and simple visual feedback.
///
/// Scene setup:
/// 1. Create a Canvas: GameObject > UI > Canvas.
/// 2. On the Canvas, add UI Text objects for Shots, Hits, Misses, Accuracy, and Average Reaction Time.
/// 3. Optional for Phase 3: add Text objects for Session Time and Session Complete.
/// 4. Add this UIManager script to the Canvas or to an empty "UIManager" GameObject.
/// 5. Drag each Text object into the matching fields in the Inspector.
/// 6. For a crosshair, create either:
///    - UI > Text with "+" centered on the screen, then assign it to Crosshair Text, or
///    - UI > Image centered on the screen, then assign it to Crosshair Image.
/// 7. Optional: create a small centered Text such as "HIT" and assign it to Hit Feedback Text.
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

    [Header("Session Text")]
    [SerializeField] private Text sessionTimeText;
    [SerializeField] private Text sessionCompleteText;

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
        SetSessionCompleteVisible(false);

        if (ScoreManager.Instance != null)
        {
            ScoreManager.Instance.SetUIManager(this);
            RefreshStats(ScoreManager.Instance);
        }

        RefreshSession();
    }

    private void Update()
    {
        RefreshSession();
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

    private void RefreshSession()
    {
        SessionManager sessionManager = SessionManager.Instance;

        if (sessionManager == null)
        {
            SetText(sessionTimeText, "Time: --");
            SetSessionCompleteVisible(false);
            return;
        }

        SetText(sessionTimeText, $"Time: {Mathf.CeilToInt(sessionManager.RemainingTime)}");

        if (sessionManager.IsSessionComplete)
        {
            ShowSessionComplete();
        }
        else
        {
            SetSessionCompleteVisible(false);
        }
    }

    public void ShowSessionComplete()
    {
        if (sessionCompleteText == null)
        {
            return;
        }

        sessionCompleteText.text = "SESSION COMPLETE\nPress R to Restart";
        SetSessionCompleteVisible(true);
    }

    private void SetSessionCompleteVisible(bool isVisible)
    {
        if (sessionCompleteText == null)
        {
            return;
        }

        sessionCompleteText.gameObject.SetActive(isVisible);
        sessionCompleteText.enabled = isVisible;
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
