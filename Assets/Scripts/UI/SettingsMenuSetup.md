# Settings Menu

## Automatic Setup

SessionManager adds SettingsMenuManager if none exists in the scene. Without an
assigned panel, it creates a legacy UI SettingsPanel on a separate overlay Canvas
and adds an EventSystem if necessary. No scene rewiring is required.

Escape opens settings during an active session and closes it to resume.
Escape does nothing on the start menu or summary. End Session uses the existing
summary and cleanup flow. R still restarts from the summary.

Gameplay pauses through Time.timeScale and explicit input guards. Score and
targets are preserved. Reaction timing excludes paused time. Changing mode clears
targets and resets spawn timing without resetting score or session time.
The FPS counter uses unscaled time and continues updating while paused.

## Optional Custom Panel

1. Add SettingsMenuManager to an always-active manager object before Play.
   Do not place the component on the SettingsPanel that it hides.
2. Create SettingsPanel under an active Canvas with a legacy Text title, Settings.
   Add Continue and End Session legacy Buttons and assign both references.
3. Add a legacy Dropdown for FPS Limit and one for Game Mode. Assign their
   references; options and listeners are populated automatically at startup.
   FPS choices are 30, 60, 90, 120, Unlimited. Mode choices are Static Targets,
   Moving Targets, Flick Targets, Reaction Targets.
4. Add a Slider and a legacy Text for sensitivity. Assign Sensitivity Slider and
   Sensitivity Text. The script sets the range to 0.5-5.0 and reads the player's
   current sensitivity when settings open.
5. Optionally assign FPS Limit Text and Selected Mode Text, plus Player and
   Performance Settings. Those components are otherwise found automatically.
6. Keep the Canvas and EventSystem active. Do not duplicate these callbacks in
   Inspector OnClick/OnValueChanged: assigned controls are wired automatically.

FPS and sensitivity changes apply immediately; Unlimited sets targetFrameRate to
-1. VSync stays disabled. Settings are scene-local and are not saved across R
restart. Static/moving/flick/reaction rules still come from TargetSpawner.

## Play Mode Checks

- Start a session, open settings with Escape, and verify timer/targets freeze.
- Verify cursor unlocks, aiming/shooting is blocked, and FPS still updates.
- Change cap and sensitivity, Continue, and confirm timer resumes with same score.
- Change mode while paused: targets clear, score stays, and new targets follow the
  selected mode after Continue.
- End Session: targets clear and final summary appears. R returns to start menu.
- Escape on start or summary must not end/restart anything.
