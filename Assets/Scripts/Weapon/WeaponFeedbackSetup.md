# First-Person Shooting Feedback

Attach WeaponViewModel.cs to the WeaponViewModel child under Main Camera. This
object should contain the arms/pistol visuals, not the Camera or PlayerController.
Attaching to its nested arms object also works. Imported arms can contain a Camera
child; this no longer disables feedback. Missing a camera ancestor only warns.
If an Animator drives the arms, use an outer WeaponViewModel wrapper for this script
and put the Animator/model inside it. This avoids competing transform animation.
Gun finds the component below its assigned camera or player; manual assignment
in Gun's Weapon View Model field also works.
Gun also tries FindObjectOfType if the camera/player searches find no component.
Use one WeaponViewModel component on the wrapper or arms, not both. The script
animates only its own local transform. Keep Gun's Player Camera assigned to the
actual Main Camera, not the imported Camera inside the arms.

Optional muzzle flash: create an effect child at the pistol muzzle and assign it.
Keep the parent weapon active. The flash starts hidden and is enabled for 0.04s
per shot. Use an actual visible mesh, light, or particle effect; an empty object
alone has no visible output. Do not assign the camera or weapon root as the flash.

Optional audio: add an AudioSource to WeaponViewModel, turn Play On Awake off,
set Spatial Blend to 0 for first-person sounds, and assign it. Assign Shoot, Hit,
Headshot, and Miss clips as available. Missing fields are safe and produce no sound.
Audio uses PlayOneShot so outcome sounds can overlap the gunshot.

Recoil modifies only the wrapper's local pose. Camera-center raycasting remains
unchanged, so visual recoil does not change aim. Recoil Snappiness controls the
kick response, Recoil Return Speed controls recovery, and repeated shots refresh
the impulse without building unlimited offset. Disabling the component hides the
flash and restores its original local pose.

Play-mode checks: verify camera/player stay still when firing without movement;
arms/pistol kick and return; flash resets after repeated shots; body/head/miss sounds
match results, including gray reaction misses; missing clips/flash work without
errors; Escape ends shooting and R returns to the menu normally.
