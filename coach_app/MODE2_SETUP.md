Mode 2 uses Unity Head HitZone colliders and target IsHittable state. No detection, recording, synthetic mouse events or automatic shooting.

Start a game session, enable Mode 2 via the Unity menu button or Coach Mode 2 / Start Assist, return focus to Unity, then hold RMB. Nearest means world distance among visible, unoccluded, hittable heads inside the 25 degree cone. Release RMB stops correction that frame. F8/ESC or focus loss latches OFF; press Start again to rearm. Pauses/menus/session end block corrections. Stop in Unity is immediate; Coach Stop arrives on the next IPC poll (normally 100 ms); connection loss expires the remote lease in 600 ms. Sensitivity and training modes retain their original controls. Assist tuning is on the Player AssistStatePublisher component.

Legacy visual tools/data are quarantined under legacy_mode2, outside runtime imports and Unity Assets; ignored captures remain preserved there. Do not run legacy tools. Credentials and Keychain are unchanged.

Rollback: git switch to a branch at 9d3fbc2. Quarantined ignored captures are not part of Git; retain legacy_mode2 when rolling back.
