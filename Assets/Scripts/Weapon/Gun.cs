using UnityEngine;

/// <summary>
/// Simple hitscan gun that shoots from the center of the player camera.
/// Add this to a weapon object or the player camera.
/// </summary>
public class Gun : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private Camera playerCamera;

    [Header("Shooting")]
    [SerializeField] private float range = 100f;
    [SerializeField] private float fireRate = 6f;

    public int ShotsFired { get; private set; }

    private float nextFireTime;

    private void Awake()
    {
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

        if (Physics.Raycast(ray, out RaycastHit hitInfo, range))
        {
            Target target = hitInfo.collider.GetComponentInParent<Target>();

            if (target != null)
            {
                target.Hit();
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
