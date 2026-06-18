using UnityEngine;

/// <summary>
/// Lightweight movement for aim trainer targets.
/// The target moves around the position where it spawned.
/// </summary>
public class TargetMovement : MonoBehaviour
{
    public enum MovementType
    {
        Horizontal,
        Vertical,
        Circular
    }

    [Header("Movement")]
    [SerializeField] private MovementType movementType = MovementType.Horizontal;
    [SerializeField] private float movementSpeed = 2f;
    [SerializeField] private float movementDistance = 2f;

    [Header("Randomness")]
    [SerializeField] private bool randomizeSpeed = true;
    [SerializeField] private float minSpeedMultiplier = 0.8f;
    [SerializeField] private float maxSpeedMultiplier = 1.2f;

    private Vector3 spawnLocalPosition;
    private float movementDirection = 1f;
    private float phaseOffset;
    private float speedMultiplier = 1f;

    private void Start()
    {
        spawnLocalPosition = transform.localPosition;
        RandomizeMovement();
    }

    private void Update()
    {
        // Each target has its own direction, phase, and speed multiplier.
        // This keeps targets from moving in the same direction at the same time.
        float time = (Time.time * movementSpeed * speedMultiplier * movementDirection) + phaseOffset;

        if (movementType == MovementType.Horizontal)
        {
            MoveHorizontal(time);
        }
        else if (movementType == MovementType.Vertical)
        {
            MoveVertical(time);
        }
        else
        {
            MoveCircular(time);
        }
    }

    public void Configure(MovementType newMovementType, float newMovementSpeed, float newMovementDistance)
    {
        movementType = newMovementType;
        movementSpeed = newMovementSpeed;
        movementDistance = newMovementDistance;
    }

    private void RandomizeMovement()
    {
        // Direction controls left/right, up/down, or clockwise/counter-clockwise.
        movementDirection = Random.value < 0.5f ? -1f : 1f;

        // Phase offset means every target starts at a different point in its movement.
        phaseOffset = Random.Range(0f, Mathf.PI * 2f);

        if (randomizeSpeed)
        {
            speedMultiplier = Random.Range(minSpeedMultiplier, maxSpeedMultiplier);
        }
        else
        {
            speedMultiplier = 1f;
        }
    }

    private void MoveHorizontal(float time)
    {
        float offset = Mathf.Sin(time) * movementDistance;
        transform.localPosition = spawnLocalPosition + new Vector3(offset, 0f, 0f);
    }

    private void MoveVertical(float time)
    {
        float offset = Mathf.Sin(time) * movementDistance;
        transform.localPosition = spawnLocalPosition + new Vector3(0f, offset, 0f);
    }

    private void MoveCircular(float time)
    {
        float xOffset = Mathf.Cos(time) * movementDistance;
        float yOffset = Mathf.Sin(time) * movementDistance;
        transform.localPosition = spawnLocalPosition + new Vector3(xOffset, yOffset, 0f);
    }
}
