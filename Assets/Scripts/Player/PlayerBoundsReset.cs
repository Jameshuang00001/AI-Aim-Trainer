using UnityEngine;

/// <summary>Attach to the player root; recover safely if it leaves the arena.</summary>
[RequireComponent(typeof(CharacterController))]
public class PlayerBoundsReset : MonoBehaviour
{
    [SerializeField] private float minY = -5f;
    [SerializeField, Min(1f)] private float maxDistanceFromOrigin = 50f;
    [SerializeField] private Vector3 resetPosition = new Vector3(0f, 1f, 0f);

    private CharacterController characterController;
    private PlayerController playerController;

    private void Awake()
    {
        characterController = GetComponent<CharacterController>();
        playerController = GetComponent<PlayerController>();
    }

    private void LateUpdate()
    {
        // Check after movement so falling or leaving bounds is corrected this frame.
        Vector3 position = transform.position;
        if (position.y >= minY && position.sqrMagnitude <= maxDistanceFromOrigin * maxDistanceFromOrigin)
            return;

        // Temporarily disable the controller so teleporting does not use stale contacts.
        bool wasEnabled = characterController.enabled;
        characterController.enabled = false;
        transform.position = resetPosition;
        if (playerController != null) playerController.ResetMovementVelocity();
        characterController.enabled = wasEnabled;
        Debug.Log("Player was reset to arena spawn because they left bounds.", this);
    }
}
