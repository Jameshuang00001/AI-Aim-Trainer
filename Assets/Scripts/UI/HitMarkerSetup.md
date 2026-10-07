# Hit Marker Setup

1. Under the gameplay Canvas, create an empty UI object named HitMarkerRoot with
   a RectTransform centered at anchors/pivot (0.5, 0.5), position (0, 0), scale 1.
   Add HitMarkerUI to this object and assign its RectTransform as Marker Root.
2. Create eight separate UI > Image children. Use solid white Images (no sprite
   required), with nonzero alpha. Assign four to Body Hit Lines and the other four
   to Headshot Extra Lines, in array order. Do not assign the crosshair Image to
   either array. Images should be dedicated to this effect, without layout groups.
3. Assign HitMarkerUI to UIManager's Hit Marker UI field. If unassigned, UIManager
   searches once, including inactive objects. The marker root may start inactive;
   each show call enables it. Keep the Canvas and its ancestors active, and ensure
   any parent CanvasGroup has alpha 1. The script hides only line GameObjects at
   the end and restores their alpha to 1 for reuse.
   Existing crosshair colors and hit/miss Text feedback are unaffected.

The four body lines occupy diagonal directions; headshots add four cardinal lines.
Line rotation, size, and spacing are handled by the script. Distances specify each
line's center distance from the crosshair in Canvas units. Defaults: duration 0.12s,
distance 14 to 28, length 18, thickness 3. A new hit restarts the effect cleanly.

# EnemyTarget Hit Zones

Add a small trigger SphereCollider or CapsuleCollider and HitZone to the head bone
or a child following it. Choose Head and assign the root Target as Target Parent.
Add HitZone to each body/limb collider object, choose Body, and assign the same root
Target. Collider and HitZone must be on the same GameObject. Parent auto-discovery
works when the Target is an ancestor. Keep all zones under the target hierarchy so
the death logic disables them together.

Resize the existing root body capsule so it covers the torso/legs but not the head.
A body collider covering the head can intercept the ray first and report Body.
Head and body both score a normal hit and trigger the same death animation. Targets
without HitZone retain body-hit fallback. Early gray reaction hits are misses and
do not display a marker. No headshot statistic is added yet.

Play-mode checks: shoot body, limb, and head separately and confirm 4/4/8 lines.
Check repeated hits restart the fade, the crosshair color never changes, reaction
misses show no marker, and session end/restart and humanoid death still work.

Console diagnostics: accepted hits log "Body hit detected" or "Headshot detected",
followed by "Body hit marker shown" or "Headshot marker shown". A missing marker
component logs a setup message. If both messages appear but nothing renders, check
the eight Image references, active Canvas/parents, CanvasGroup alpha, clipping,
and marker root scale/position. Use separate line Images, never the crosshair.
