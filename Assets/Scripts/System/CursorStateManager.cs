using System.Collections;
using UnityEngine;

/// <summary>Single owner of cursor state and gameplay input permission.</summary>
[DefaultExecutionOrder(-900)]
public class CursorStateManager : MonoBehaviour
{
    public static CursorStateManager Instance { get; private set; }
    public bool GameplayInputEnabled { get; private set; }
    private Coroutine relockRoutine;
    private int inputResumeAfterFrame = -1;
    public bool CanReadGameplayInput => GameplayInputEnabled && Application.isFocused &&
        IsGameViewFocused && Cursor.lockState == CursorLockMode.Locked &&
        Time.frameCount > inputResumeAfterFrame;
    private static bool IsGameViewFocused
    {
        get
        {
#if UNITY_EDITOR
            var window = UnityEditor.EditorWindow.focusedWindow;
            return window != null && window.GetType().Name == "GameView";
#else
            return true;
#endif
        }
    }

    public static CursorStateManager GetOrCreate()
    {
        if (Instance == null)
        {
            CursorStateManager existing = FindObjectOfType<CursorStateManager>();
            if (existing != null) Instance = existing;
            else new GameObject("CursorStateManager").AddComponent<CursorStateManager>();
        }
        return Instance;
    }

    private void Awake()
    {
        if (Instance != null && Instance != this) { Destroy(this); return; }
        Instance = this;
    }

    public void EnterGameplayCursorMode()
    {
        SessionManager session = SessionManager.Instance;
        if (session == null || !session.IsSessionActive || session.IsSummaryOpen) return;
        session.SetPaused(false);
        Time.timeScale = 1f;
        GameplayInputEnabled = true;
        FocusEditorGameView();
        ApplyGameplayLock();
        Debug.Log("Cursor -> Gameplay locked");
        if (relockRoutine != null) StopCoroutine(relockRoutine);
        relockRoutine = StartCoroutine(RelockCursorNextFrame());
    }

    public void EnterMenuCursorMode()
    {
        GameplayInputEnabled = false;
        if (relockRoutine != null) StopCoroutine(relockRoutine);
        relockRoutine = null;
        if (SessionManager.Instance != null) SessionManager.Instance.SetPaused(true);
        if (Cursor.lockState != CursorLockMode.None) Cursor.lockState = CursorLockMode.None;
        if (!Cursor.visible) Cursor.visible = true;
        Debug.Log("Cursor -> Menu unlocked");
    }

    private void ApplyGameplayLock()
    {
        // Avoid repeatedly asking the native Editor to warp/lock an already locked cursor.
        if (Cursor.lockState != CursorLockMode.Locked)
        {
            Cursor.lockState = CursorLockMode.Locked;
            // Discard the transition frame's potentially recentered mouse delta.
            inputResumeAfterFrame = Time.frameCount;
        }
        if (Cursor.visible) Cursor.visible = false;
    }

    private IEnumerator RelockCursorNextFrame()
    {
        // Runs even at timeScale zero; cancels if another menu opens meanwhile.
        yield return null;
        if (GameplayInputEnabled && Application.isFocused && IsGameViewFocused)
        {
            ApplyGameplayLock();
        }
        relockRoutine = null;
    }

    private void LateUpdate()
    {
        if (!Application.isFocused || !IsGameViewFocused) return;
        if (GameplayInputEnabled) ApplyGameplayLock();
        else
        {
            if (Cursor.lockState != CursorLockMode.None) Cursor.lockState = CursorLockMode.None;
            if (!Cursor.visible) Cursor.visible = true;
        }
    }

    private void FocusEditorGameView()
    {
#if UNITY_EDITOR
        // Locking the cursor cannot restore input to an unfocused Editor Game view.
        // Focus the existing view only on explicit gameplay entry, never every frame.
        foreach (UnityEditor.EditorWindow window in Resources.FindObjectsOfTypeAll<UnityEditor.EditorWindow>())
        {
            if (window.GetType().Name != "GameView") continue;
            window.Focus();
            break;
        }
#endif
    }

    private void OnApplicationFocus(bool focused)
    {
        inputResumeAfterFrame = Time.frameCount;
        if (focused && GameplayInputEnabled && IsGameViewFocused) ApplyGameplayLock();
    }

    private void OnDestroy()
    {
        if (Instance == this) Instance = null;
    }
}
