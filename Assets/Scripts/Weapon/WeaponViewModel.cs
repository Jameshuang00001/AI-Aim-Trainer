using System.Collections;
using UnityEngine;

/// <summary>Attach to the weapon/arms child, never the camera or player root.</summary>
public class WeaponViewModel : MonoBehaviour
{
    [Header("Visual Recoil")]
    [SerializeField] private Vector3 recoilPositionOffset = new Vector3(0f, 0f, 1f);
    [SerializeField] private Vector3 recoilRotationOffset = new Vector3(1f, 0f, 0f);
    [SerializeField, Min(0f)] private float recoilReturnSpeed = 18f;
    [SerializeField, Min(0f)] private float recoilSnappiness = 35f;

    [Header("Muzzle Flash")]
    [SerializeField] private GameObject muzzleFlash;
    [SerializeField, Min(0f)] private float muzzleFlashDuration = 0.04f;

    [Header("Audio")]
    [SerializeField] private AudioSource audioSource;
    [SerializeField] private AudioClip shootClip;
    [SerializeField] private AudioClip hitClip;
    [SerializeField] private AudioClip headshotClip;
    [SerializeField] private AudioClip missClip;

    private Vector3 originalLocalPosition;
    private Quaternion originalLocalRotation;
    private Vector3 targetPositionOffset;
    private Vector3 targetRotationOffset;
    private Vector3 currentPositionOffset;
    private Vector3 currentRotationOffset;
    private Coroutine flashRoutine;
    private bool initialized;
    private bool canApplyRecoil;

    private void Awake()
    {
        // Imported arms may contain their own Camera child. That is valid and must
        // not disable feedback. Only the component's own transform receives recoil.
        Camera cameraParent = transform.parent != null
            ? transform.parent.GetComponentInParent<Camera>() : null;
        if (cameraParent == null)
            Debug.LogWarning("WeaponViewModel has no camera parent; shooting feedback will still work.", this);
        // If attached directly to a Camera/Player by mistake, allow flash/audio
        // but never change that Camera/Player transform.
        canApplyRecoil = GetComponent<Camera>() == null && GetComponent<PlayerController>() == null;
        originalLocalPosition = transform.localPosition;
        originalLocalRotation = transform.localRotation;
        initialized = true;
        if (audioSource == null) audioSource = GetComponent<AudioSource>();
        // A flash must be a separate effect object, not an ancestor containing this script.
        if (muzzleFlash != null && transform.IsChildOf(muzzleFlash.transform))
        {
            Debug.LogWarning("Muzzle Flash must not be the weapon root, camera, or an ancestor.", this);
            muzzleFlash = null;
        }
        if (muzzleFlash != null) muzzleFlash.SetActive(false);
    }

    public void PlayShootFeedback()
    {
        if (!initialized) return;
        if (!enabled) enabled = true;
        if (!gameObject.activeInHierarchy)
        {
            Debug.LogWarning("WeaponViewModel must be active to animate shooting feedback.", this);
            return;
        }
        // Refresh a bounded impulse instead of accumulating unlimited recoil.
        targetPositionOffset = recoilPositionOffset;
        targetRotationOffset = recoilRotationOffset;
        PlayClip(shootClip);
        if (muzzleFlash != null)
        {
            if (flashRoutine != null) StopCoroutine(flashRoutine);
            flashRoutine = StartCoroutine(ShowMuzzleFlash());
        }
    }

    public void PlayHitFeedback(HitZoneType zone)
    {
        PlayClip(zone == HitZoneType.Head ? headshotClip : hitClip);
    }

    public void PlayMissFeedback()
    {
        PlayClip(missClip);
    }

    private void PlayClip(AudioClip clip)
    {
        if (audioSource != null && audioSource.isActiveAndEnabled && clip != null)
            audioSource.PlayOneShot(clip);
    }

    private IEnumerator ShowMuzzleFlash()
    {
        muzzleFlash.SetActive(true);
        yield return new WaitForSecondsRealtime(muzzleFlashDuration);
        if (muzzleFlash != null)
        {
            muzzleFlash.SetActive(false);
        }
        flashRoutine = null;
    }

    private void LateUpdate()
    {
        if (!initialized || !canApplyRecoil) return;
        // Exponential smoothing keeps the response consistent across frame rates.
        float snap = 1f - Mathf.Exp(-recoilSnappiness * Time.deltaTime);
        float restore = 1f - Mathf.Exp(-recoilReturnSpeed * Time.deltaTime);
        currentPositionOffset = Vector3.Lerp(currentPositionOffset, targetPositionOffset, snap);
        currentRotationOffset = Vector3.Lerp(currentRotationOffset, targetRotationOffset, snap);
        targetPositionOffset = Vector3.Lerp(targetPositionOffset, Vector3.zero, restore);
        targetRotationOffset = Vector3.Lerp(targetRotationOffset, Vector3.zero, restore);
        transform.localPosition = originalLocalPosition + currentPositionOffset;
        transform.localRotation = originalLocalRotation * Quaternion.Euler(currentRotationOffset);
    }

    private void OnDisable()
    {
        if (flashRoutine != null) StopCoroutine(flashRoutine);
        flashRoutine = null;
        if (!initialized) return;
        if (muzzleFlash != null) muzzleFlash.SetActive(false);
        targetPositionOffset = currentPositionOffset = Vector3.zero;
        targetRotationOffset = currentRotationOffset = Vector3.zero;
        if (canApplyRecoil)
        {
            transform.localPosition = originalLocalPosition;
            transform.localRotation = originalLocalRotation;
        }
    }
}
