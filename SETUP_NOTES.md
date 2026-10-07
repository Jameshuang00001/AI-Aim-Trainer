# Phase 6: Start Menu

## Shooting Range Spawn Area

TargetSpawner now defaults to ForwardRectangle. Assign EnemyTarget and keep Spawn
Targets On Ground enabled. Assign Player Transform to the player root or camera.
Assign Shooting Platform to the platform hierarchy root; if omitted, the script
tries to find an active object named ShootingPlatform. Its collider footprint is
excluded even when Ground Layers contains only the arena floor. The platform must
have enabled colliders for footprint exclusion.

For a fixed range, create an empty SpawnAreaCenter in front of the platform and
assign it. Spawn Area Width (12) and Depth (14) define a world-aligned X/Z rectangle
centered there; center rotation does not rotate the rectangle. Y comes from ground
raycasts plus Ground Offset, not the center height. Candidates behind the player's
current horizontal forward direction are rejected, so keep the player facing the
range and the center clearly ahead.

Without a center, Width controls lateral spread and Forward Area Min Z (8) / Max Z
(22) control distance along the player's horizontal forward direction. Depth is
only used with an assigned center. Face Player On Spawn defaults on and applies
upright yaw rotation, assuming the model faces local +Z.

AroundPlayer preserves the previous forward-distance/lateral-radius placement.
Primitive fallback remains floating; grounded humanoids use ground hits. Failed
positions retry up to Spawn Attempts, then skip that spawn interval. Moving
targets retain their existing spawn-centered movement; this rectangle restricts
initial spawning, not the full movement path.

Play-mode checks: test each training mode with fixed center and player-relative
placement, confirm humanoids face the player and never spawn on the platform or
behind the player, and verify ground placement, hits, death, Escape summary, and
R restart. Use Ground Layers containing only the range floor where practical.

## Humanoid Roaming and Death Grounding

Grounded prefabs with an Animator now use random roaming in Moving Targets mode.
TargetMovement's Random Roaming defaults on. Movement Distance limits the horizontal
radius around the spawn point; Movement Speed is world units per second. Random
move periods (1.2-2.5s) alternate with random pauses (0.4-1.0s). Turn Speed controls
how quickly the target faces its actual travel direction. The model should face
local +Z. IsMoving is false while paused or blocked. Root motion remains disabled.
IsMoving has a 0.25-second stopping grace period and only changes when its value
changes. Death/component disabling stops walking immediately. Each straight move
chooses a sufficiently long endpoint within the spawn radius and keeps that
direction for the full phase. Short segments slow down to fill the minimum phase;
long segments may take longer than Max Move Duration to respect Movement Speed.
Boundary/ground failures do not shorten phases. Circular movement stays continuous
unless Pause Circular Movement is checked. Existing serialized Inspector duration
overrides should be updated manually to the new defaults if needed.
Ground probes reject missing ground and abrupt steps. This is lightweight roaming,
not NavMesh pathfinding. Use an open arena; complex obstacle navigation is not included.

Death behavior is intentionally simple: disable colliders and TargetMovement,
set IsMoving false, trigger Death once, then destroy after Death Destroy Delay
(default 1.5 seconds). Root motion stays disabled. There are no death ground
raycasts, upward corrections, saved-height restores, or visual-root locks.
The animation plays its normal pose even if the body sinks slightly into the floor.

Verify in Play mode: Moving Targets walk facing travel, stop into Idle, then resume
in varied directions; their radius remains bounded. Shoot standing and moving targets
and check the normal death animation plays without a scripted height adjustment.
Select the floor layer for spawning so props are not mistaken for ground.

## Gameplay Polish Settings

### Target Collision and Player Safety

Targets now use trigger colliders and kinematic, gravity-free rigidbodies if a
prefab includes one. Gun raycasts explicitly detect triggers. Keep Target and
TargetMovement on separate target objects, outside the player/camera hierarchy.
Targets never change parent transforms. Hit feedback disables all target colliders
and movement before scoring or pulsing the target's own scale.

Spawning previously placed a solid collider at the player position before moving
it away and syncing physics. This could overlap the CharacterController during
replacement spawns. New targets become non-physical before that physics sync.
Spawn overlap checks still include trigger targets so placement remains safe.

PlayerController uses fresh raw horizontal input each frame and only stores
vertical velocity. ResetMovementVelocity() clears vertical velocity and both jump
windows. PlayerBoundsReset is added automatically at runtime if missing. Add it
to the Player root in the Inspector to persist custom settings: Min Y = -5,
Max Distance From Origin = 50 (world-origin distance), Reset Position = (0, 1, 0).
Choose a clear reset point above a ground collider. It temporarily disables the
CharacterController while resetting, clears movement, and logs the reason.

Play-mode regression checks: stand still and repeatedly hit targets, especially
flick replacements. Walk through moving targets; they must not block/push you.
Release movement keys and verify horizontal motion stops immediately. Set Physics
Queries Hit Triggers off and confirm targets can still be shot. Fall below Min Y
or move beyond the distance limit; verify the reset and exact safety log. Check
jumping after reset, reaction misses, Escape summaries, and R menu restart.

- Session duration now defaults to 30 seconds; SampleScene's saved value is also
  30. Other scenes retain their Inspector overrides. Escape ends an active session
  through the same summary/cleanup path as the timer. It does nothing in the menu.
- TargetSpawner exposes Min Spawn Height (1), Max Spawn Height (4), Ground Layers,
  Ground Ray Height/Distance, and Spawn Attempts (10). Heights measure the target
  root above detected ground; its actual renderer/collider bounds determine the
  minimum safe height. Assign ground colliders to a Ground layer and select that
  layer in Ground Layers when possible. Triggers are ignored. No detected ground
  means the candidate is rejected, not placed at an assumed floor height.
- Vertical/circular movement needs additional clearance equal to Movement
  Distance. Increase Max Spawn Height for very large prefabs or wide movement
  arcs. If there is no safe position within the height range after retries, that
  spawn interval is skipped. Horizontal placement uses the player's flattened
  forward direction, so camera pitch does not change target height.
- PlayerController exposes Coyote Time and Jump Buffer Time, both 0.1 seconds.
  Keep gravity negative. The player still uses CharacterController, with no
  Rigidbody. Jump input is consumed once and horizontal/vertical velocity share
  one Move call.

Play-mode checks: Escape during each mode should clear targets, freeze stats,
show the summary, and allow R restart. Look steeply down/up while spawning and
test large target scales; targets should appear above ground or skip spawning.
Jump while walking/sprinting, just after walking off an edge, and just before
landing. Confirm buffered presses produce one jump, not repeated airborne jumps.

1. Keep GameModeManager, SessionManager, ScoreManager, and UIManager on active
   scene objects. SessionManager now waits for Start; it does not begin on load.
2. On the active Canvas, create StartMenuPanel and stretch its RectTransform to
   cover the screen. Keep UIManager outside this panel so it continues running
   after the menu is hidden. Use the existing HUD behind it; the HUD can remain
   visible, but movement, shooting, scoring, spawning, and the timer are inactive.
3. Add UI > Legacy > Text for the selected mode/title. Add four UI > Legacy >
   Button objects labeled Static Targets, Moving Targets, Flick Targets, and
   Reaction Targets. Add a fifth button labeled Start. Use legacy Text labels.
4. Ensure the scene has an EventSystem with StandaloneInputModule and the Canvas
   has a GraphicRaycaster. These allow normal Unity UI clicks. Keep the menu
   panel and buttons on an active Canvas with adequate spacing and readable text.
5. Assign Start Menu Panel, Mode Select Text, the four mode buttons, and Start
   Button in UIManager. Keep the existing Training Mode Text and Mode Instruction
   Text assignments. UIManager automatically connects assigned buttons at Start.

## Optional Manual OnClick Wiring

Instead of assigning button references, leave those button fields empty and wire
each Button's Inspector On Click list: press +, drag the GameModeManager object
into the target slot, and choose the corresponding method:

- Static: GameModeManager.SetStaticTargetsMode()
- Moving: GameModeManager.SetMovingTargetsMode()
- Flick: GameModeManager.SetFlickTargetsMode()
- Reaction: GameModeManager.SetReactionTargetsMode()
- Start: GameModeManager.StartGame()

Use either automatic references or manual OnClick wiring, not both. Mode selection
updates the menu label and HUD instructions immediately. Selection locks when
Start begins the session. Add the current scene to File > Build Settings > Scenes
In Build so R can reload it. Reloading returns to the start menu.

## Play Mode Checks

- On scene load, cursor is visible, the menu is shown, and time/stats stay fixed.
- Click each mode and verify its label/instructions update before starting.
- Click Start: menu hides, cursor locks, countdown begins, and the selected mode
  controls targets. Reaction targets wait gray before turning red.
- Let time expire: targets clear, summary appears, and stats stop changing.
- Press R: the scene reloads to the menu and waits for Start again.
