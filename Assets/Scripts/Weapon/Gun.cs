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

    [Header("Shooting")]
    [SerializeField] private float range = 100f;
    [SerializeField] private float fireRate = 6f;

    public int ShotsFired { get; private set; }

    private float nextFireTime;

    private void Awake()
    {
        if (uiManager == null) uiManager = FindObjectOfType<UIManager>();
        if (playerCamera == null)
        {
            playerCamera = Camera.main;
        }
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

        ScoreManager scoreManager = ScoreManager.Instance;
        if (scoreManager != null)
        {
            scoreManager.RegisterShot();
        }

        if (playerCamera == null)
        {
            Debug.LogWarning("Gun needs a camera reference before it can shoot.");
            RegisterMiss(scoreManager);
            return;
        }

        Ray ray = playerCamera.ViewportPointToRay(new Vector3(0.5f, 0.5f, 0f));
        Debug.DrawRay(ray.origin, ray.direction * range, Color.red, 0.25f);

        // Explicitly include trigger targets even when global trigger queries are off.
        if (Physics.Raycast(ray, out RaycastHit hitInfo, range,
            Physics.DefaultRaycastLayers, QueryTriggerInteraction.Collide))
        {
            HitZone hitZone = hitInfo.collider.GetComponent<HitZone>();
            Target target = hitZone != null ? hitZone.TargetParent
                : hitInfo.collider.GetComponentInParent<Target>();
            HitZoneType zone = hitZone != null ? hitZone.Zone : HitZoneType.Body;

            if (target != null)
            {
                if (target.TryHit(zone))
                {
                    Debug.Log(zone == HitZoneType.Head ? "Headshot detected" : "Body hit detected", this);
                    if (uiManager == null) uiManager = FindObjectOfType<UIManager>();
                    if (uiManager != null)
                    {
                        if (zone == HitZoneType.Head) uiManager.ShowHeadshotMarker();
                        else uiManager.ShowBodyHitMarker();
                    }
                    else Debug.LogWarning("UIManager is missing; hit marker cannot be displayed.", this);
                }
                return;
            }
        }

        RegisterMiss(scoreManager);
    }

    private void RegisterMiss(ScoreManager scoreManager)
    {
        if (scoreManager != null)
        {
            scoreManager.RegisterMiss();
        }
    }
}
