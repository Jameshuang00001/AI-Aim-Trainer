using UnityEngine;

public enum HitZoneType { Body, Head }

/// <summary>Add to the same GameObject as a head/body trigger collider.</summary>
[RequireComponent(typeof(Collider))]
public class HitZone : MonoBehaviour
{
    [SerializeField] private HitZoneType zone = HitZoneType.Body;
    [SerializeField] private Target targetParent;
    public HitZoneType Zone => zone;
    public Target TargetParent => targetParent != null ? targetParent : GetComponentInParent<Target>();

    private void Awake()
    {
        if (targetParent == null) targetParent = GetComponentInParent<Target>();
    }
}
