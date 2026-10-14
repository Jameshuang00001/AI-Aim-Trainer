# Reaction and Flick Modes

## Reaction

TargetSpawner now spawns one stationary, enlarged bot at the fixed range center.
Assign Reaction Spawn Point to an empty Transform in front of the shooting
platform for precise placement, or use Spawn Area Center. With neither assigned,
the first bot uses the midpoint of the player's forward range. Ground raycasts
still place humanoid roots on the floor. Keep the point in front of the player,
off the platform, above valid ground. The first successful world position is
cached until session cleanup/reset, so subsequent bots appear at exactly that spot.

Default scale multiplier is 1.75. The bot starts in its normal color, then turns
red after a random wait strictly longer than 3 seconds (default maximum 6).
Early shots count as misses but never record reaction time or play death.
A valid red hit records time since the signal, turns the bot green, and plays
death. After death finishes, a 0.5-second delay precedes the next bot.
Scaled timing excludes time paused in Settings.

## Flick

A valid hit immediately spawns the next randomly placed target. The previous
bot can finish its death animation with disabled colliders. Both live targets and
dying bots remain tracked for reset/end-session cleanup. Hits records each
accepted kill once and serves as the Flick kill count, including in the summary.

## Optional Legacy Text References

On UIManager, assign Latest Reaction Text to a legacy UI Text object under the
gameplay Canvas. Its visibility follows mode.
Latest reaction displays three decimal places.
The existing average reaction text remains available.

Without Latest Reaction Text, the existing average reaction text displays latest
and average on two lines; give that Text enough height for both lines. Without
an extra kill text, Hits shows the Flick kill count in both gameplay and summary.
Changing mode or time limit resets reaction and hit stats alongside the other stats.

## Play Mode Checks

- Reaction: only one larger bot; early shot is a miss; red delay exceeds 3s.
- Hit red: green death, one reaction result, then next bot at the identical spot.
- Pause during waiting/death: timing and animation freeze and resume normally.
- Flick: next bot appears on hit, while the old bot is still falling.
- Mode/time reset: live/dying bots disappear and stats reset.
- End Session opens current stats without removing bots or resetting score.
  Escape resumes the same practice session. Timed expiry switches to Unlimited.
