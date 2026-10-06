# Phase 4 Setup

1. Create an empty GameObject named GameModeManager and attach GameModeManager.cs.
2. Select Current Mode in its Inspector before pressing Play. Without this manager,
   the trainer defaults to StaticTargets. Select modes between sessions; changing
   the Inspector during Play affects new spawns, not targets already in the scene.
3. On TargetSpawner, tune Moving Targets settings, Flick Spawn Delay, and the
   minimum/maximum Reaction Delay. The mode now replaces the old moving-target toggle.
4. Under the existing Canvas, create two UI > Legacy > Text objects. Assign them
   to UIManager's Training Mode Text and Mode Instruction Text fields. Make the
   instruction rectangle wide enough for the reaction-mode sentence.
5. Target prefabs should have a collider and a Target component on their root.
   Use a Built-in Standard material for the normal, gray, and red colors. Primitive
   fallback targets already have a renderer and collider. Color overrides apply
   to child renderers too, without modifying the shared material.

Static targets stay still. Moving targets use TargetMovement. Flick targets allow
one target at a time and replace successful hits after Flick Spawn Delay. Reaction
targets stay gray for a random delay, then turn red. Shooting gray counts as a miss
and leaves the target alive. Reaction time is measured from the red signal.

Keep SessionManager in the scene to stop spawning and scoring at session end.
The existing R restart reloads the scene and uses the Inspector-selected mode.

Play-mode checks: test each mode, shoot a gray reaction target, then a red one;
confirm only the red hit destroys it. In flick mode, confirm a successful hit
replaces the target quickly. Let the timer expire and verify targets disappear,
stats stop changing, the completion message appears, and R restarts the session.
