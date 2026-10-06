# Phase 6: Start Menu

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
