using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;

/// <summary>
/// Keep this component on an active manager, not on the hidden panel.
/// If no panel is assigned, a simple legacy UI is created automatically.
/// </summary>
public class SettingsMenuManager : MonoBehaviour
{
    [SerializeField] private GameObject settingsPanel;
    [SerializeField] private Button continueButton;
    [SerializeField] private Button endSessionButton;
    [SerializeField] private Dropdown fpsLimitDropdown;
    [SerializeField] private Dropdown modeDropdown;
    [SerializeField] private Slider sensitivitySlider;
    [SerializeField] private Text sensitivityText;
    [SerializeField] private Text fpsLimitText;
    [SerializeField] private Text selectedModeText;
    [SerializeField] private PlayerController player;
    [SerializeField] private PerformanceSettings performanceSettings;

    private readonly int[] frameRates = { 30, 60, 90, 120, -1 };
    private readonly string[] modeNames = { "Static Targets", "Moving Targets", "Flick Targets", "Reaction Targets" };
    private Font font;

    private void Start()
    {
        if (player == null) player = FindObjectOfType<PlayerController>();
        if (performanceSettings == null) performanceSettings = FindObjectOfType<PerformanceSettings>();
        if (settingsPanel == null) BuildDefaultPanel();
        if (continueButton != null) continueButton.onClick.AddListener(ContinueSession);
        if (endSessionButton != null) endSessionButton.onClick.AddListener(EndSession);
        if (fpsLimitDropdown != null)
        {
            fpsLimitDropdown.ClearOptions();
            fpsLimitDropdown.AddOptions(new System.Collections.Generic.List<string> { "30", "60", "90", "120", "Unlimited" });
            fpsLimitDropdown.onValueChanged.AddListener(SetFPSOption);
        }
        if (modeDropdown != null)
        {
            modeDropdown.ClearOptions();
            modeDropdown.AddOptions(new System.Collections.Generic.List<string>(modeNames));
            modeDropdown.onValueChanged.AddListener(SetModeOption);
        }
        if (sensitivitySlider != null)
        {
            sensitivitySlider.minValue = 0.5f;
            sensitivitySlider.maxValue = 5f;
            sensitivitySlider.wholeNumbers = false;
            sensitivitySlider.onValueChanged.AddListener(SetSensitivity);
        }
        HidePanel();
    }

    public void ToggleSettings()
    {
        SessionManager session = SessionManager.Instance;
        if (session == null || !session.IsSessionActive) return;
        if (session.IsPaused) ContinueSession();
        else
        {
            session.SetPaused(true);
            settingsPanel.SetActive(true);
            settingsPanel.transform.SetAsLastSibling();
            RefreshControls();
        }
    }

    public void ContinueSession()
    {
        HidePanel();
        if (SessionManager.Instance != null) SessionManager.Instance.SetPaused(false);
        if (EventSystem.current != null) EventSystem.current.SetSelectedGameObject(null);
    }

    public void EndSession()
    {
        HidePanel();
        if (SessionManager.Instance != null) SessionManager.Instance.EndSession();
    }

    public void HidePanel()
    {
        if (settingsPanel != null) settingsPanel.SetActive(false);
    }

    public void SetFPSOption(int index)
    {
        if (index < 0 || index >= frameRates.Length) return;
        if (performanceSettings != null) performanceSettings.SetFrameRate(frameRates[index]);
        else
        {
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = frameRates[index];
        }
        RefreshControls();
    }

    public void SetModeOption(int index)
    {
        if (index < 0 || index >= modeNames.Length) return;
        if (GameModeManager.Instance != null) GameModeManager.Instance.SetMode((AimTrainingMode)index);
        RefreshControls();
    }

    public void SetSensitivity(float value)
    {
        if (player != null) player.SetMouseSensitivity(value);
        if (sensitivityText != null) sensitivityText.text = $"Sensitivity: {value:F1}";
    }

    private void RefreshControls()
    {
        int cap = performanceSettings != null ? performanceSettings.TargetFrameRate : Application.targetFrameRate;
        int capIndex = System.Array.IndexOf(frameRates, cap);
        if (fpsLimitDropdown != null && capIndex >= 0) fpsLimitDropdown.SetValueWithoutNotify(capIndex);
        if (fpsLimitText != null) fpsLimitText.text = "FPS Limit: " + (cap <= 0 ? "Unlimited" : cap.ToString());
        int mode = GameModeManager.Instance != null ? (int)GameModeManager.Instance.CurrentMode : 0;
        if (modeDropdown != null) modeDropdown.SetValueWithoutNotify(mode);
        if (selectedModeText != null) selectedModeText.text = "Mode: " + modeNames[mode];
        float sensitivity = player != null ? player.MouseSensitivity : 2f;
        if (sensitivitySlider != null) sensitivitySlider.SetValueWithoutNotify(sensitivity);
        if (sensitivityText != null) sensitivityText.text = $"Sensitivity: {sensitivity:F1}";
    }

    private void BuildDefaultPanel()
    {
        // A separate overlay keeps the menu independent of hidden gameplay panels.
        GameObject canvasObject = new GameObject("SettingsCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        Canvas canvas = canvasObject.GetComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 100;
        CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(800f, 650f);
        scaler.matchWidthOrHeight = 0.5f;
        if (EventSystem.current == null)
            new GameObject("EventSystem", typeof(EventSystem), typeof(StandaloneInputModule));
        font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        RectTransform panel = CreateRect("SettingsPanel", canvasObject.transform, Vector2.zero, Vector2.zero);
        panel.anchorMin = Vector2.zero;
        panel.anchorMax = Vector2.one;
        panel.offsetMin = panel.offsetMax = Vector2.zero;
        settingsPanel = panel.gameObject;
        panel.gameObject.AddComponent<Image>().color = new Color(0.06f, 0.07f, 0.08f, 0.96f);
        CreateText("Title", "Settings", panel, new Vector2(0f, 235f), new Vector2(600f, 40f));
        fpsLimitText = CreateText("FPSLimit", "FPS Limit", panel, new Vector2(0f, 185f), new Vector2(600f, 32f));
        for (int i = 0; i < frameRates.Length; i++)
        {
            int option = i;
            Button button = CreateButton(i == 4 ? "Unlimited" : frameRates[i].ToString(), panel,
                new Vector2(-240f + i * 120f, 140f), new Vector2(110f, 38f));
            button.onClick.AddListener(() => SetFPSOption(option));
        }
        sensitivityText = CreateText("Sensitivity", "Sensitivity", panel, new Vector2(0f, 90f), new Vector2(600f, 32f));
        RectTransform sliderRect = CreateRect("SensitivitySlider", panel, new Vector2(0f, 45f), new Vector2(560f, 28f));
        Image track = sliderRect.gameObject.AddComponent<Image>();
        track.color = new Color(0.3f, 0.3f, 0.3f);
        sensitivitySlider = sliderRect.gameObject.AddComponent<Slider>();
        RectTransform handle = CreateRect("Handle", sliderRect, Vector2.zero, new Vector2(20f, 28f));
        Image handleImage = handle.gameObject.AddComponent<Image>();
        handleImage.color = Color.white;
        sensitivitySlider.handleRect = handle;
        sensitivitySlider.targetGraphic = handleImage;
        selectedModeText = CreateText("Mode", "Mode", panel, new Vector2(0f, -10f), new Vector2(600f, 32f));
        for (int i = 0; i < modeNames.Length; i++)
        {
            int option = i;
            Button button = CreateButton(modeNames[i], panel,
                new Vector2(i % 2 == 0 ? -150f : 150f, -60f - i / 2 * 50f), new Vector2(280f, 40f));
            button.onClick.AddListener(() => SetModeOption(option));
        }
        continueButton = CreateButton("Continue", panel, new Vector2(-150f, -190f), new Vector2(280f, 44f));
        endSessionButton = CreateButton("End Session", panel, new Vector2(150f, -190f), new Vector2(280f, 44f));
    }

    private RectTransform CreateRect(string name, Transform parent, Vector2 position, Vector2 size)
    {
        RectTransform rect = new GameObject(name, typeof(RectTransform)).GetComponent<RectTransform>();
        rect.SetParent(parent, false);
        rect.anchorMin = rect.anchorMax = new Vector2(0.5f, 0.5f);
        rect.anchoredPosition = position;
        rect.sizeDelta = size;
        return rect;
    }

    private Text CreateText(string name, string value, Transform parent, Vector2 position, Vector2 size)
    {
        Text text = CreateRect(name, parent, position, size).gameObject.AddComponent<Text>();
        text.font = font;
        text.fontSize = 22;
        text.alignment = TextAnchor.MiddleCenter;
        text.color = Color.white;
        text.text = value;
        text.raycastTarget = false;
        return text;
    }

    private Button CreateButton(string label, Transform parent, Vector2 position, Vector2 size)
    {
        RectTransform rect = CreateRect(label, parent, position, size);
        Image background = rect.gameObject.AddComponent<Image>();
        background.color = new Color(0.22f, 0.25f, 0.27f);
        Button button = rect.gameObject.AddComponent<Button>();
        button.targetGraphic = background;
        CreateText("Label", label, rect, Vector2.zero, size);
        return button;
    }
}
