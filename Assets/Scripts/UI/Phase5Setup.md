# Phase 5 Setup

1. Under the existing Canvas, create UI > Panel named SummaryPanel. Use a dark
   background and a centered RectTransform, roughly 480 by 420 pixels.
2. Add UI > Legacy > Text as a child named SummaryText. Stretch it inside the panel
   with 24-pixel margins, use a readable font size (20 is a good starting point),
   white text, and middle-center alignment. Leave enough height for all lines.
3. Assign SummaryPanel and SummaryText to UIManager's Session Summary fields.
   SummaryPanel may start inactive. Keep UIManager on the active Canvas or a
   separate active object, not inside SummaryPanel. Keep the Canvas active too.
4. Optionally add a separate legacy Text near the crosshair, assign it to Miss
   Feedback Text, and choose Miss Feedback Duration. This Text may start inactive.
5. On target prefabs, tune Hit Color, Hit Feedback Duration, and Hit Scale
   Multiplier. Primitive fallback targets use the defaults: green, 0.12 seconds,
   and a 1.2 scale pulse. Use Built-in Standard materials for color feedback.

At session end, the panel copies final shots, hits, misses, accuracy, average
reaction time, and mode. The existing SessionManager R shortcut reloads the scene.
UIManager exposes ShowSummaryPanel() and HideSummaryPanel(). The old completion
Text remains a fallback if the panel references are missing.

Hits score immediately, stop target movement, and disable colliders during the
pulse. Flick replacements wait until the pulse finishes, keeping one target at
a time. Session-end cleanup also removes targets currently playing hit feedback.
Early gray reaction shots and shots that hit no target both show MISS.

Check in Play mode: hit several targets, miss, shoot an inactive reaction target,
and let the timer expire during a hit pulse. Verify final totals match the HUD,
the initially inactive summary appears, feedback text clears, and R resets the
scene. Check the panel at your smallest supported Game view resolution.
