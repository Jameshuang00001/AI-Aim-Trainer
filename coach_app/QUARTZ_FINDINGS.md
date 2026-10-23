# Quartz findings from existing manual trials

Source: `assist-9f912fce598f45299b4210f2b54896bc.jsonl` under
`~/Library/Logs/AI-Aim-Trainer/quartz_diagnostics/`. Original logs were read only.
The other JSONL present during the audit was empty.

## Recorded observations

- Eight activated, posted and completed trials; one rejected activation.
- PID delivery: **5/5** observed responses, expected axis/rotation signs in all five.
  Four have approximately Mouse X **+0.05**, Mouse Y **-0.05**, yaw/pitch **+0.1 degrees**,
  each with one nonzero Unity input frame. One has approximately **+0.10/-0.10**
  and **+0.2/+0.2 degrees**, with two nonzero input frames.
- HID-tap delivery: **3/3** observed responses, expected signs in all three;
  approximately **+0.05/-0.05** and **+0.1/+0.1 degrees**, one nonzero frame each.
- All posts requested the same **+2/+2** event delta. Neither reverse-direction nor
  no-event stationary control trials were recorded. No physical baseline was recorded.
- Old records retain only observation-window totals, not pre/pulse/post snapshots.
  Result timestamps are about **373-409 ms** after the posted log entry. This is
  the assessment delay, **not the event-to-camera latency**.

## Conclusion

Both methods show consistent direction and repeatable post-window association.
That is stronger evidence than a single success flag. It does not establish where
inside the window the input occurred or exclude physical movement/key-trigger
contamination. The doubled PID response is a repeatability concern, not proof of
either coalescing, duplicate injection, or a physical movement source.

**Neither method is independently verified yet.** No continuous Head Lock is
enabled, no existing camera bounds were relaxed, and no synthetic pulses were
automatically generated for this analysis.

## Controlled repeats

The updated runner writes schema-2 per-packet snapshots and separate zero-input
pre/pulse/post totals. F4 is a stationary no-event control. Use the existing
authorized Terminal and enabled diagnostic Unity publisher; no additional Unity
rebuild is needed if it already supplied the cumulative counters for these logs.

```sh
.venv/bin/python -m coach_app.quartz_delivery_test --window-id CURRENT_ID --direction positive
```

With focused/locked gameplay and your physical mouse untouched, manually alternate
**F4, F6, F4, F7, F4**. Wait **at least two seconds after each key press**, until the
result is printed. Collect at least five trials per delivery method and five quiet
controls. Do not press F5 during stationary trials; it is only for deliberate
physical-mouse baselines. F8/ESC stops immediately.

Then stop and restart with `--direction negative` for fixed **-2/-2** pulses, still
one fresh F6/F7 press per test. Repeat the same controls and trial counts. Expected
reverse response is negative X, positive Y, negative yaw and negative pitch. Keep
the camera away from pitch clamps. No gain or magnitude is automatically tuned.

Each test captures a minimum 0.3-second quiet pre-window, at least 0.4 seconds for
pulse observation and another 0.4 seconds of post observation. Snapshots arrive at
the existing ~25 Hz cadence; they are not per-HID-event timestamps. A controlled
pass requires a quiet pre-window, expected response and direction, and quiet post-
window. Stationary controls must show no input/camera response throughout. Signs
are normalized for the negative trial; the original strict **0.005 to 3 degrees**
response magnitude bounds remain unchanged.

Analyze old and new files without sending events:

```sh
.venv/bin/python -m coach_app.analyze_quartz_trials --output /tmp/quartz-analysis.json
```

New reports include arrival-relative onset brackets when traces exist. These are
local packet reception brackets, not precise hardware/Unity event latency; packet
delay and physical contamination remain limitations. No report automatically sets
`independently_verified` or enables Head Lock. Actual controlled repetitions still
require your explicit key presses; they were not fabricated by unit tests.
