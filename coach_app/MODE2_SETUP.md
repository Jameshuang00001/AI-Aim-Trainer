Game startup shows a draggable AI floating companion. Click AI to open Coach. All Mode 2 Start/Stop and submode selection are in Coach; no gameplay overlay button.

Mode 2 / Hold RMB: return focus to Unity and hold RMB for bounded, smooth camera assistance.
Mode 2 / Single-click correction: explicitly Start, then manually click left mouse once per shot. Only that shot ray is corrected toward the nearest visible valid head in the configured cone before the original hit test. The camera does not teleport. Holding left mouse does not repeat in this submode; no automatic firing is added. If no valid head exists the original shot ray is used.

Both modes retain session, focus, cursor, occlusion, hit-state and emergency-stop gates. Switching mode stops assistance and requires Start. F8/ESC and focus loss latch OFF. Coach Stop arrives on the next IPC poll, normally 100ms; remote lease expires after 600ms without updates. A mode selected after focus has already left Unity can be armed in Coach and becomes eligible when Unity regains focus.

The companion uses native AppKit floating/all-Spaces window behavior, with no Quartz, screen capture or Accessibility dependency. Startup health never reads credentials; only the existing report functionality needs the Nebius credential.

Local builds embed the source project location as a non-secret StreamingAssets hint. Moving this build to another machine requires providing Coach and COACH_APP_ROOT. Old visual tools remain quarantined in legacy_mode2. Rollback checkpoint before this revision: 3d54f71.
