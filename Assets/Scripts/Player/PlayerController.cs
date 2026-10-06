using UnityEngine;

/// <summary>
/// Basic first-person player controller for an offline aim trainer.
/// Add this to a Player object with a CharacterController component.
/// Assign the player Camera to playerCamera in the Inspector.
/// </summary>
[RequireComponent(typeof(CharacterController))]
public class PlayerController : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private Camera playerCamera;

    [Header("Movement")]
    [SerializeField] private float movementSpeed = 6f;
    [SerializeField] private float sprintSpeed = 10f;
    [SerializeField] private float jumpHeight = 1.5f;
    [SerializeField] private float gravity = -20f;

    [Header("Jump Forgiveness")]
    [SerializeField, Min(0f)] private float coyoteTime = 0.1f;
    [SerializeField, Min(0f)] private float jumpBufferTime = 0.1f;

    [Header("Mouse Look")]
    [SerializeField] private float mouseSensitivity = 2f;
    [SerializeField] private float verticalLookLimit = 85f;

    private CharacterController characterController;
    private float verticalVelocity;
    private float lastGroundedTime = float.NegativeInfinity;
    private float lastJumpPressedTime = float.NegativeInfinity;
    private float cameraPitch;

    private void Awake()
    {
        characterController = GetComponent<CharacterController>();
        // Existing player scenes get the safety net without needing Inspector rewiring.
        if (GetComponent<PlayerBoundsReset>() == null) gameObject.AddComponent<PlayerBoundsReset>();

        if (playerCamera == null)
        {
            playerCamera = GetComponentInChildren<Camera>();
        }
    }

    private void Start()
    {
        // Leave the cursor free for menu buttons. StartGame captures it later.
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
    }

    private void Update()
    {
        if (SessionManager.Instance == null || !SessionManager.Instance.IsSessionActive)
        {
            ResetMovementVelocity();
            return;
        }
        HandleMouseLook();
        HandleMovement();
    }

    private void HandleMouseLook()
    {
        float mouseX = Input.GetAxis("Mouse X") * mouseSensitivity;
        float mouseY = Input.GetAxis("Mouse Y") * mouseSensitivity;

        transform.Rotate(Vector3.up * mouseX);

        cameraPitch -= mouseY;
        cameraPitch = Mathf.Clamp(cameraPitch, -verticalLookLimit, verticalLookLimit);

        if (playerCamera != null)
        {
            playerCamera.transform.localRotation = Quaternion.Euler(cameraPitch, 0f, 0f);
        }
    }

    public void ResetMovementVelocity()
    {
        verticalVelocity = 0f;
        lastGroundedTime = float.NegativeInfinity;
        lastJumpPressedTime = float.NegativeInfinity;
    }

    private void HandleMovement()
    {
        bool isGrounded = characterController.isGrounded;

        // Sample the button once, before moving. Remember early landing presses.
        if (Input.GetButtonDown("Jump")) lastJumpPressedTime = Time.time;

        if (isGrounded && verticalVelocity <= 0f)
        {
            lastGroundedTime = Time.time;
            verticalVelocity = -2f;
        }

        // Raw axes stop immediately on release; only vertical velocity persists.
        float inputX = Input.GetAxisRaw("Horizontal");
        float inputZ = Input.GetAxisRaw("Vertical");

        Vector3 moveDirection = transform.right * inputX + transform.forward * inputZ;
        moveDirection.y = 0f;
        moveDirection = Vector3.ClampMagnitude(moveDirection, 1f);

        float currentSpeed = Input.GetKey(KeyCode.LeftShift) ? sprintSpeed : movementSpeed;
        bool hasBufferedJump = Time.time - lastJumpPressedTime <= jumpBufferTime;
        bool canJump = Time.time - lastGroundedTime <= coyoteTime;
        if (hasBufferedJump && canJump)
        {
            verticalVelocity = Mathf.Sqrt(Mathf.Max(0f, jumpHeight) * -2f * gravity);
            // Consume both windows to prevent a second jump during takeoff.
            lastJumpPressedTime = float.NegativeInfinity;
            lastGroundedTime = float.NegativeInfinity;
        }

        verticalVelocity += gravity * Time.deltaTime;
        Vector3 velocity = moveDirection * currentSpeed;
        velocity.y = verticalVelocity;
        CollisionFlags collisions = characterController.Move(velocity * Time.deltaTime);
        if ((collisions & CollisionFlags.Above) != 0 && verticalVelocity > 0f)
            verticalVelocity = 0f;
    }
}
