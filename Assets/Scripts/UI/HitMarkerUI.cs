using System.Collections;
using UnityEngine;
using UnityEngine.UI;

/// <summary>Independent radial hit lines. Never changes the crosshair image or color.</summary>
public class HitMarkerUI : MonoBehaviour
{
    [SerializeField] private RectTransform markerRoot;
    [SerializeField] private Image[] bodyHitLines = new Image[4];
    [SerializeField] private Image[] headshotExtraLines = new Image[4];
    [SerializeField, Min(0.01f)] private float showDuration = 0.12f;
    [SerializeField] private float startDistance = 14f;
    [SerializeField] private float endDistance = 28f;
    [SerializeField, Min(1f)] private float lineLength = 18f;
    [SerializeField, Min(1f)] private float lineThickness = 3f;

    private Coroutine animationRoutine;

    private void Awake()
    {
        if (markerRoot == null) markerRoot = GetComponent<RectTransform>();
        HideMarkers();
    }

    public void ShowBodyHit()
    {
        Show(false);
    }

    public void ShowHeadshot()
    {
        Show(true);
    }

    private void Show(bool headshot)
    {
        if (markerRoot == null) markerRoot = GetComponent<RectTransform>();
        if (markerRoot == null)
        {
            Debug.LogWarning("HitMarkerUI needs a Marker Root RectTransform.", this);
            return;
        }
        // Activate before checking hierarchy state or starting a coroutine.
        // Awake may run here for the first time when the root started inactive.
        markerRoot.gameObject.SetActive(true);
        gameObject.SetActive(true);
        enabled = true;
        if (!gameObject.activeInHierarchy || !markerRoot.gameObject.activeInHierarchy)
        {
            Debug.LogWarning("HitMarkerUI has an inactive parent. Keep its Canvas and parents active.", this);
            return;
        }
        if (animationRoutine != null) StopCoroutine(animationRoutine);
        HideMarkers();
        // Set up visible lines at full opacity before the first animation frame.
        UpdateLines(bodyHitLines, 45f, startDistance, 1f);
        if (headshot) UpdateLines(headshotExtraLines, 0f, startDistance, 1f);
        animationRoutine = StartCoroutine(AnimateMarkers(headshot));
    }

    private IEnumerator AnimateMarkers(bool headshot)
    {
        float elapsed = 0f;
        while (elapsed < Mathf.Max(0.01f, showDuration))
        {
            float progress = elapsed / Mathf.Max(0.01f, showDuration);
            float distance = Mathf.Lerp(startDistance, endDistance, progress);
            // Four diagonal lines for body hits; four cardinal extras for headshots.
            UpdateLines(bodyHitLines, 45f, distance, 1f - progress);
            if (headshot) UpdateLines(headshotExtraLines, 0f, distance, 1f - progress);
            elapsed += Time.unscaledDeltaTime;
            yield return null;
        }
        HideMarkers();
        animationRoutine = null;
    }

    private void UpdateLines(Image[] lines, float firstAngle, float distance, float opacity)
    {
        if (lines == null) return;
        for (int i = 0; i < Mathf.Min(4, lines.Length); i++)
        {
            Image line = lines[i];
            if (line == null) continue;
            float angle = firstAngle + i * 90f;
            float radians = angle * Mathf.Deg2Rad;
            RectTransform rect = line.rectTransform;
            if (rect.parent != markerRoot) rect.SetParent(markerRoot, false);
            rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0.5f, 0.5f);
            rect.localScale = Vector3.one;
            rect.sizeDelta = new Vector2(lineLength, lineThickness);
            rect.anchoredPosition3D = new Vector3(Mathf.Cos(radians), Mathf.Sin(radians), 0f) * distance;
            rect.localRotation = Quaternion.Euler(0f, 0f, angle);
            Color color = line.color;
            color.a = Mathf.Clamp01(opacity); // Absolute alpha; never reuse last fade's zero.
            line.color = color;
            line.raycastTarget = false;
            line.gameObject.SetActive(true);
            line.enabled = true;
        }
    }

    private static void HideLines(Image[] lines)
    {
        if (lines == null) return;
        foreach (Image line in lines)
        {
            if (line == null) continue;
            Color color = line.color;
            color.a = 1f;
            line.color = color;
            line.gameObject.SetActive(false);
        }
    }

    private void HideMarkers()
    {
        HideLines(bodyHitLines);
        HideLines(headshotExtraLines);
    }

    private void OnDisable()
    {
        if (animationRoutine != null) StopCoroutine(animationRoutine);
        animationRoutine = null;
        HideMarkers();
    }
}
