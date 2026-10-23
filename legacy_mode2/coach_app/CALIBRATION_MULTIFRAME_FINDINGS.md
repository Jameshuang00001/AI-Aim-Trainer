# Calibration multi-frame investigation - 2026-10-23

## Evidence, not an acceptance-limit change

Read the local calibration JSONL files and matching reports under
`~/Library/Logs/AI-Aim-Trainer/camera_calibration/`. Across the available reports,
31 internally consistent single-frame nonzero trials pass with approximately
0.05 degrees per requested delta. Five internally consistent two-frame trials
fail with approximately **0.10 degrees per requested delta**. No correctly
summed two-frame split was found in these calibration reports.

The latest four failures are below. Filenames have prefix `assist-` and suffix
`.report.json`; matching `.jsonl` files contain the dispatch and sample records.
Every Mouse Y is zero; pitch changes are zero to float precision.

| Report ID | Trial | Request X | Input frame indices | Each Mouse X | Total Mouse X | Total yaw |
| --- | --- | --- | --- | --- | --- | --- |
| f3ca6ca84be6498e8a767d8e6c23c00f | 7 | +2 | 25154, 25155 | +0.05, +0.05 | +0.10 | +0.19998 deg |
| b5b273e341d84ff28678aaed18eabda7 | 12 | +2 | 22364, 22365 | +0.05, +0.05 | +0.10 | +0.20001 deg |
| eccab7fc3dcb489ea06e5bb15903370b | 3 | -2 | 17858, 17859 | -0.05, -0.05 | -0.10 | -0.20001 deg |
| a2d415f4c571402d812d3f8f3d56dc9b | 8 | -2 | 15215, 15216 | -0.05, -0.05 | -0.10 | -0.19998 deg |

Each individual frame rotates yaw about +/-0.10 degrees. Frame separation is
16.62, 16.83, 17.09 and 17.00 ms respectively. Both frames occur in the pulse
observation window. First-frame Unity UTC timestamps follow the logged post
record by approximately 0.90, 0.62, 0.95 and 1.32 ms respectively. These UTC
differences are observational, not precision event-latency measurements.

All four tests have exactly one logged `posted` record for their test ID,
returned native dispatch, AX trusted, matching destination/foreground PID
69405, focused/locked input frames, and quiet pre/post windows. Frame sequence,
counters, consumed input and rotation sums reconcile. The older two-frame
`cadce2a59384499db32e9a007cdb52c7` report has the same doubled pattern.

Direction is correct and timing is correlated, but **total magnitude is double
the single-frame baseline**. This is not evidence for a normal response being
split over two frames. The records cannot distinguish duplicate native/input
delivery from concurrent same-direction physical input. Quiet neighboring
windows do not exclude physical contamination during the pulse. Do not infer
provenance from the API returning or from internally consistent frame history.

## Exact source change

- Keep the one-frame acceptance gate. No real split-response evidence supports
  increasing the permitted count. Continuous Head Lock is not enabled.
- The shared Matrix validator now optionally checks total rotation and total
  Unity input against a previously established same-axis calibration gain.
  It uses the existing 20% gain tolerance, not a wider tolerance.
- Calibration supplies its prior valid same-axis gain. Previously its gain
  check only ran AFTER all other checks passed, so a count failure masked the
  simultaneous doubled-response failure. Magnitude is now evaluated even when
  frame count, direction or frame consistency fails.
- Report `total_magnitude` separately from `frame_count_valid`, direction,
  frame-history consistency and the existing broad rotation bounds. Record
  chronological status, frame gaps and input span in `input_timing`; existing
  pre/pulse/post window, freshness, menu, focus, axis and emergency gates remain.
- A hypothetical 0.025 + 0.025 Mouse X / 0.10-degree total split passes magnitude
  diagnostics but remains rejected by the count gate. It is a regression fixture,
  not a claim that this delivery pattern has been observed or authorized.

## Verification and build impact

Offline tests cover single-frame, hypothetical correctly summed two-frame,
doubled two-frame, wrong-axis, missing history, cancellation/contamination and
excessive responses. A full mocked calibration verifies both rejection reasons
are retained. Read-only replay tests check all four local failed trials.

From the project root:

```sh
.venv/bin/python -m unittest coach_app.test_camera_calibration coach_app.test_quartz_matrix coach_app.test_controlled_assist
```

No real mouse events were sent. No Unity C# or sensitivity changes, training,
Coach.app rebuild, standalone rebuild, commits or pushes are needed for this
investigation. Packaged Coach keeps its previous code until explicitly rebuilt;
a later Coach-only rebuild would add the clearer diagnostics, not authorize
these doubled responses. No new live calibration is claimed here.
