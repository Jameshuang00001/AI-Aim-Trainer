using UnityEngine;

/// <summary>
/// Simple hitscan gun that shoots from the center of the player camera.
/// Add this to a weapon object or the player camera.
/// </summary>
public class Gun : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private Camera playerCamera;
    [SerializeField] private UIManager uiManager;
    [SerializeField] private WeaponViewModel weaponViewModel;

    [Header("Shooting")]
    [SerializeField] private float range = 100f;
    [SerializeField] private float fireRate = 6f;

    [Header("Aim Debug")]
    [SerializeField] private bool drawAimDebugRay = false;
    [SerializeField, Min(0f)] private float debugRayDuration = 0.1f;
    [SerializeField] private bool showDebugHitPoint;

    public int ShotsFired { get; private set; }

    private float nextFireTime;

    private void Awake()
    {
        if (uiManager == null) uiManager = FindObjectOfType<UIManager>();
        if (playerCamera == null)
            Debug.LogWarning("Assign the Player's Main Camera to Gun's Player Camera field.", this);
        FindWeaponViewModel();
    }

    private static bool IsWeaponCamera(Camera camera)
    {
        if (camera.name == "ViewModelCamera") return true;
        if (camera.GetComponentInParent<WeaponViewModel>() != null) return true;
        // Also recognize the visual hierarchy before a feedback script is attached.
        for (Transform parent = camera.transform.parent; parent != null; parent = parent.parent)
            if (parent.name == "WeaponViewModel") return true;
        return false;
    }

    private void FindWeaponViewModel()
    {
        if (weaponViewModel != null) return;
        if (playerCamera != null)
            weaponViewModel = playerCamera.GetComponentInChildren<WeaponViewModel>(true);
        if (weaponViewModel == null)
        {
            PlayerController player = GetComponentInParent<PlayerController>();
            if (player == null && playerCamera != null)
                player = playerCamera.GetComponentInParent<PlayerController>();
            if (player != null) weaponViewModel = player.GetComponentInChildren<WeaponViewModel>(true);
        }
        if (weaponViewModel == null) weaponViewModel = FindObjectOfType<WeaponViewModel>();
    }

    private void Update()
    {
        if (Input.GetMouseButton(0) && Time.time >= nextFireTime)
        {
            Shoot();
        }
    }

    private void Shoot()
    {
        if (SessionManager.Instance == null || !SessionManager.Instance.IsSessionActive)
        {
            return;
        }

        nextFireTime = Time.time + 1f / fireRate;
        ShotsFired++;
        FindWeaponViewModel();
        if (weaponViewModel != null) weaponViewModel.PlayShootFeedback();

        ScoreManager scoreManager = ScoreManager.Instance;
        if (scoreManager != null)
        {
            scoreManager.RegisterShot();
        }

        // Never replace the Inspector camera with a camera found in the scene.
        if (playerCamera == null || IsWeaponCamera(playerCamera))
        {
            Debug.LogWarning("Assign Player Camera to the player's Main Camera, not a weapon/arms camera.", this);
            RegisterMiss(scoreManager);
            return;
        }

        Ray ray = playerCamera.ViewportPointToRay(new Vector3(0.5f, 0.5f, 0f));
        if (drawAimDebugRay)
        {
            Debug.DrawRay(ray.origin, ray.direction * range, Color.red, debugRayDuration);
        }

        // Explicitly include trigger targets even when global trigger queries are off.
        if (Physics.Raycast(ray, out RaycastHit hitInfo, range,
            Physics.DefaultRaycastLayers, QueryTriggerInteraction.Collide))
        {
            if (showDebugHitPoint) CreateDebugHitPoint(hitInfo.point);
            HitZone hitZone = hitInfo.collider.GetComponent<HitZone>();
            Target target = hitZone != null ? hitZone.TargetParent
                : hitInfo.collider.GetComponentInParent<Target>();
            HitZoneType zone = hitZone != null ? hitZone.Zone : HitZoneType.Body;

            if (target != null)
            {
                if (target.TryHit(zone))
                {
                    if (weaponViewModel != null) weaponViewModel.PlayHitFeedback(zone);
                    if (uiManager == null) uiManager = FindObjectOfType<UIManager>();
                    if (uiManager != null)
                    {
                        if (zone == HitZoneType.Head) uiManager.ShowHeadshotMarker();
                        else uiManager.ShowBodyHitMarker();
                    }
                    else Debug.LogWarning("UIManager is missing; hit marker cannot be displayed.", this);
                }
                else if (weaponViewModel != null)
                {
                    // Target already registers early reaction shots as misses.
                    // Play audio here without registering the miss a second time.
                    weaponViewModel.PlayMissFeedback();
                }
                return;
            }
        }

        RegisterMiss(scoreManager);
    }

    private void CreateDebugHitPoint(Vector3 point)
    {
        GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        marker.name = "Debug Aim Hit Point";
        // Debug visuals must not intercept later shots or physically touch the player.
        marker.layer = 2; // Unity's built-in Ignore Raycast layer.
        Collider markerCollider = marker.GetComponent<Collider>();
        markerCollider.enabled = false;
        Destroy(markerCollider);
        marker.transform.position = point;
        marker.transform.localScale = Vector3.one * 0.05f;
        MaterialPropertyBlock color = new MaterialPropertyBlock();
        color.SetColor("_Color", Color.red);
        marker.GetComponent<Renderer>().SetPropertyBlock(color);
        Destroy(marker, 1f);
    }

    private void RegisterMiss(ScoreManager scoreManager)
    {
        if (weaponViewModel != null) weaponViewModel.PlayMissFeedback();
        if (scoreManager != null)
        {
            scoreManager.RegisterMiss();
        }
    }
}
