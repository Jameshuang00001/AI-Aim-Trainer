# Isolated seven-case Quartz matrix

## Observed versus unproven

Read-only native construction probe on this Mac, 2026-10-22 (no events posted):

| Case | Requested/read-back delta | Timestamp at creation / after setting delta |
| --- | --- | --- |
| Zero construction probe | 0, 0 | 0 / 0 |
| Horizontal positive | 2, 0 | 0 / 0 |
| Horizontal negative | -2, 0 | 0 / 0 |
| Vertical positive | 0, 2 | 0 / 0 |
| Vertical negative | 0, -2 | 0 / 0 |
| Diagonal positive | 2, 2 | 0 / 0 |
| Diagonal negative | -2, -2 | 0 / 0 |

Zero is therefore reproducible constructor behavior on this installation, not
unique to failed single-axis events. It is **not proof that delivery accepts or
rejects zero timestamps**. Earlier successful pulses did not log timestamps.
Apple exposes separate timestamp getter/setter APIs; the local SDK header does
not promise a nonzero creation timestamp. Do not claim that a zero value is
universally invalid or silently replace it as a supposed fix.

References: [Apple timestamp API](https://developer.apple.com/documentation/coregraphics/cgevent/timestamp),
[Apple mouse event creation API](https://developer.apple.com/documentation/coregraphics/cgevent/init(mouseeventsource:mousetype:mousecursorposition:mousebutton:)).
The locally inspected header was
`/Library/Developer/CommandLineTools/SDKs/MacOSX14.4.sdk/System/Library/Frameworks/CoreGraphics.framework/Versions/A/Headers/CGEvent.h`.

Both geometries use the same source (`None`), current event location, mouse-move
type, right-button argument (not a click), delta field setters and post helper.
Only delta values differ. No timestamp setter, event-source override, click,
warp, or camera/sensitivity change is introduced by the matrix.

Historical evidence: diagonal PID pulses produced about +/-0.05 Unity axes and
+/-0.1 degrees per active axis. The 18:35 calibration also produced responses
for separate horizontal and vertical pulses. Later horizontal pulses returned
from posting but produced zero axes and zero rotation. This does not establish
that geometry or timestamps caused the change. Host identity/thread, event
delivery and Unity acceptance remain hypotheses until compared under controlled
conditions. The new seven-case live matrix has **not** been run by the agent.

## Read-only probe

From the project root, using the existing virtual environment:

```sh
.venv/bin/python -m coach_app.quartz_matrix --inspect-events
```

This creates local event objects and reads fields without posting any event.
Even the zero probe above is only construction; the live zero control below
does not create/post a synthetic event.

## Manual live matrix (standalone Test2 only by default)

1. Stop Coach calibration and the old A/B runner so UDP 8767 is free. The Coach
   can otherwise remain running; do not start its detector or Verify worker.
   Use existing Unity `Publish Quartz Diagnostics` telemetry; no Unity rebuild
   or Coach.app rebuild is needed for this separate Python diagnostic.
2. Determine the game's current window ID. Never reuse a historical ID blindly.
   Grant AX access to this diagnostic's Python/Terminal host normally if needed;
   Coach.app authorization alone need not authorize this process.
3. Run one chosen case (substitute WINDOW_ID):

   ```sh
   .venv/bin/python -m coach_app.quartz_matrix --window-id WINDOW_ID --case horizontal-positive --method pid
   ```

4. Return focus to active Unity gameplay. Close Settings/Summary; cursor must
   be locked. Wait for **READY** after at least 350 ms of valid foreground/gameplay
   state and three distinct Unity frames. Keep the mouse still. Press/release F4
   for an extra no-event control, then wait at least two seconds.
5. Press/release **F6** for ONE selected-case trial. Wait at least two seconds
   between trials, staying still through the pre/pulse/post windows. Repeat
   five times if safe. Held keys do not repeat. A silent pulse stays a failed
   result; it never becomes successful merely because posting returned.
6. **F8/Escape/Control-C stops.** Finish a case, stop the diagnostic, and repeat
   steps 3-5 for each case below. No shell command launches a pulse by itself.

| `--case` | Delta | Expected Unity axis sign | Expected camera direction |
| --- | --- | --- | --- |
| `zero` | No event | 0, 0 | None |
| `horizontal-positive` | +2, 0 | +, 0 | Right only |
| `horizontal-negative` | -2, 0 | -, 0 | Left only |
| `vertical-positive` | 0, +2 | 0, - | Down only |
| `vertical-negative` | 0, -2 | 0, + | Up only |
| `diagonal-positive` | +2, +2 | +, - | Right/down |
| `diagonal-negative` | -2, -2 | -, + | Left/up |

Repeat with `--method hid` only as an explicit second matrix; HID-tap delivery
is global, so the game-focus gates remain mandatory. Interleave cases or repeat
them in reverse order to check for time/order effects rather than interpreting
one successful case as proof of a geometry effect.

## Safety and results

### Size-bounded diagnostic transport (chunked v1)

The publisher still sends unchanged normal Coach state on **8766**. On **8767**
it now splits each serialized diagnostic snapshot into 3072-byte pieces.
Each piece is base64-encoded inside a JSON envelope containing:
`diagnostic_chunk_version=1`, `pid`, `frame`, `stream_id`, `batch_id`,
`chunk_index`, `chunk_count`, `payload_bytes`, `sha256`, and `data`.
Every actual UTF-8 envelope is measured before Send and must be **below 6000
bytes**, safely below this machine's 9216-byte UDP limit. Snapshots over 65536
bytes are rejected rather than sent. No OS networking settings are changed.

Unity logs `Quartz UDP size` every two seconds with actual serialized payload
bytes, chunk count, and smallest/largest datagram byte counts. Socket errors
now include channel/port, chunk, bytes, SocketErrorCode, native code and message,
throttled separately for Coach and Quartz so one channel cannot hide the other.

All diagnostic consumers share `diagnostic_udp.py`: matrix, A/B runner,
calibration, gameplay-state observer and one-snapshot read-only receiver. The
assembler validates bounded headers, exact chunk lengths and SHA-256, accepts
out-of-order/identical duplicate chunks, and publishes only a COMPLETE snapshot.
Conflicting chunks, bad checksum or payload/header mismatch fail closed.
Expired batches, replayed batches and late older frames cannot refresh state.
At most eight incomplete snapshots are buffered. Assembly expires at 200 ms;
freshness uses the FIRST fragment's receive time, not completion time.

UDP cannot promise delivery. The 32-frame rolling history is retained INSIDE
the reconstructed payload so a later complete snapshot can recover lost input
evidence; input_sequence/frame checks and result-log deduplication remain.
Missing chunks never produce a partial history. If frames fall out of the
rolling window, incomplete evidence fails instead of silently dropping them.
Legacy unchunked packets remain readable. No frame-count, rotation, focus,
permission or emergency thresholds have been relaxed; Head Lock stays disabled.

Measured with the in-memory 32-frame regression fixture: **10404 payload bytes**,
four serialized envelopes of **4348, 4348, 4348, 1836 bytes**. These are actual
fixture encodings, not claimed Unity runtime measurements. Unity's exact values
must be read from the rebuilt game's size logs and receiver `transport` summary.

Validation:

1. Rebuild Unity Test3 with the changed publisher. Leave Inspector ports 8766
   and 8767 as above and enable Publish Quartz Diagnostics. No sensitivity change.
2. Run the standalone, start gameplay, and move the physical mouse briefly to
   fill history. Stop other listeners on 8767 before the read-only command.
3. Using its current PID, run:

   ```sh
   .venv/bin/python -m coach_app.udp_telemetry_diagnostic --pid CURRENT_PID --timeout 5
   ```

4. Expect `valid_packet`, `mouse_frame_version=1`, schema_valid=true, and a
   `transport` summary with payload/chunk sizes all below 6000. Confirm matching
   `Quartz UDP size` entries in `~/Library/Logs/DefaultCompany/AI-Aim-Trainer/Player.log`
   (or Unity Console in Editor), without MessageSize/MessageTooLong send errors.
5. Run the matrix with `--case zero` for a no-event control; F4 must pass once
   focused gameplay is READY. This case sends no mouse events, even on F6.

   ```sh
   .venv/bin/python -m coach_app.quartz_matrix --window-id CURRENT_WINDOW_ID --expect-app AI-Aim-Trainer-Test3.app --case zero --method pid
   ```

6. Only explicitly manually request a horizontal trial afterward if desired.
   Inspect `unity_mouse_frame` entries and `mouse_frame_evidence`. Two input
   frames still fail the one-frame gate even if reconstruction is complete.
   F8/ESC still stop immediately. Calibration is not verified by transport success.

Coach.app must be rebuilt before its packaged calibration reader can understand
the new envelope; the development CLI uses the updated Python files directly.
Do not use an old packaged calibration reader as transport validation.

### Read-only UDP delivery check

Stop the matrix/calibration receiver before running this exclusive one-packet
listener. Use the CURRENT Unity PID, not a historical PID:

```sh
.venv/bin/python -m coach_app.udp_telemetry_diagnostic --pid CURRENT_PID --port 8767 --timeout 5
```

This binds only loopback, reassembles one snapshot, prints an allowlisted
packet/schema/transport summary and exits.
It never sends datagrams, imports Quartz for posting, or generates mouse input.
`bind_failed` (errno 48 on macOS usually means another listener),
`no_packet_received`, `invalid_packet` and `valid_packet` are distinct outcomes.
A valid base packet need not contain valid frame history: inspect `frame_schema`.
Matrix preconditions also show received/valid/invalid packet counts. No raw JSON
or arbitrary payload strings are printed by the standalone receiver diagnostic.

October 22 22:20 investigation, Unity PID 5413: the log has no decoded packets
and no JSON/schema rejection. `lsof` shows a connected Unity sender to 8767,
but no competing listener after the matrix exited. An exclusive 5-second
receive on 8767 timed out, whereas 8766 delivered a valid 963-byte packet from
5413. A connected UDP socket is not evidence that Send succeeded.

This host reports `net.inet.udp.maxdgram=9216`. A representative compact
32-frame history packet measures 11062 bytes; a separate inert loopback
transport probe succeeds at 1400 bytes and fails at 11062 with errno 40,
`Message too long`. Increasing Python's receive buffer cannot fix a sender
datagram-size limit. The publisher currently swallows Send SocketExceptions.
Oversized history is therefore the strongly supported sender-side cause, but
the running Unity Send exception and exact actual payload size have not been
recorded. No gameplay, ports, host UDP settings or build were changed.
A future concrete fix should bound/chunk diagnostic datagrams below the host
limit and report throttled send failures, not loosen input validation.

### Individual Unity input frames

#### Missing history in Test3: reversed serialized ports

Investigation of `assist-f4913b2154bf42d280d20a1bb13d9e27.jsonl`
(October 22, 22:06-22:07 local): all 348 sample packets contain
`mouse_frame_version: 0` and `mouse_frames: []`. This is the normal Coach state
payload, serialized BEFORE history is assigned. It is not the diagnostic
payload, which sets version 1 and serializes again. Python preserves both fields.

The current SampleScene has `coachStatePort: 8767` and
`quartzDiagnosticPort: 8766`, opposite the intended ports. Test3's compiled
assembly contains the new frame-history field names, and its `level0` contains
the corresponding reversed serialized port values. An old publisher is therefore
not the explanation supported by these packets. No build was changed during
this investigation. Correct the Inspector settings before a future Unity build:
Coach State Port **8766**, Quartz Diagnostic Port **8767**, diagnostics enabled.
Changing the source scene alone does not change a running standalone build.
Do not silently redirect the matrix to the Coach port: the Coach may already
be listening there, and this would leave the normal Coach state path wrong.

Read-only validation of existing logs (no sockets or event posting):

```sh
.venv/bin/python -m coach_app.quartz_matrix --validate-telemetry-log /absolute/path/to/assist-log.jsonl
```

Version 0 now reports `normal_coach_stream_no_frame_history_check_port_mapping`.
A missing version still reports `requires_updated_Unity_publisher`. Version 1
requires an actual array; an empty array is valid schema before input occurs,
but cannot supply evidence for nonzero input counters. Array contents and
counter reconciliation are checked separately; schema validity is not acceptance.

Rebuild the Unity standalone with the updated `AssistStatePublisher` to obtain
`mouse_frame_version=1`. Keep `Publish Quartz Diagnostics` enabled. This is a
read-only telemetry change; sensitivity and gameplay input are unchanged.
No Coach.app rebuild is needed for the command-line matrix. Older builds still
work, but report frame evidence as unavailable rather than inventing samples.

The diagnostic port includes the last 32 nonzero-input Unity frames, repeated
in subsequent packets to survive packet loss. Each contains its Unity frame
index, input sequence, UTC timestamp, Unity realtime, Mouse X/Y, raw axes,
consumed look input, yaw/pitch and per-frame angular changes, focus and lock.
These are Unity sampling timestamps, NOT native hardware-event timestamps.
The normal Coach state port does not receive this larger history.

`unity_mouse_frame` JSONL records deduplicate the repeated history during each
trial. A result also includes `mouse_frame_evidence`, which reconciles frame
sequences and sums with cumulative counters and checks per-frame direction,
consumed input/camera agreement and focus/lock. Missing/overwritten, malformed
or inconsistent history cannot pass as complete evidence. Pre/post snapshot
checks, stale telemetry checks, the 3-degree limit and emergency stops remain.

`direction_matches`, `response_in_existing_bounds`, `frame_count_valid` and
`rejected_checks` are now independent. Two same-direction frames may therefore
have correct direction and safe magnitude while STILL failing the unchanged
one-nonzero-frame rule. Even opposing per-frame movements that cancel in the
totals are flagged by the trace checks.

`unity_axis_per_requested_unit` compares aggregate Unity input to requested
Quartz delta. These are different units, not a presumed 1:1 pixel mapping.
Compare equal requested pulses across fresh manually triggered trials, including
interleaved zero controls, with the physical mouse untouched. Check whether a
two-frame response splits the usual total or doubles it. The summary retains
frame counts, direction-valid counts and consistent-trace counts for comparison.

Existing logs establish that multiple input frames were observed after one
logged post, but cannot prove they originated solely from that post. In
particular the observed .10 Unity X / .20-degree yaw was twice another trial's
.05 / .10 response, not merely a proven redistribution over frames. Whether
Quartz/Unity legitimately spreads one pulse over frames remains unverified;
no frame-count allowance is increased, and physical contamination is never
declared ruled out by a quiet baseline alone. Head Lock remains disabled.

### Precondition diagnostics

The matrix now prints and logs each precondition separately, before a manual
trial and whenever failed conditions change. It reports selected/foreground
PID, valid matching Unity telemetry received, its age in milliseconds, combined
gameplay state, cursor locked, session active, paused, AX permission, listening
UDP port and exact rejection reasons. Missing telemetry is distinct from stale
telemetry, wrong-PID packets, malformed JSON, disabled diagnostic telemetry,
foreground mismatch, permission denial and an insufficient quiet baseline.
The native pre-post gate checks these conditions again. Rejected key presses
are consumed, never queued for firing after a condition recovers.

`--port 8767` is the default; it must match Unity's Quartz Diagnostic Port.
If no valid matching telemetry has arrived, age is unknown, not a fake zero.
Last rejected UDP packet details help distinguish no packets from wrong packets.

**Older standalone builds:** individual cursor/session/pause fields are not
present in their JSON. The display says `unknown (not published by Unity)`;
it does not guess which component of `gameplay=false` failed. Legacy packets
still require `gameplay=true`, valid owner PID, fresh counters, focus and AX.

The read-only `AssistStatePublisher.cs` now publishes separate boolean fields
`application_focused`, `cursor_locked`, `session_present`, `session_active`,
`paused`, and `gameplay_input_enabled`. Version 2 also publishes panel visibility,
send time and exact gameplay blockers; see `GAMEPLAY_STATE_DIAGNOSTIC.md`.
To see these exact values in a standalone game, rebuild **Unity** with that
publisher update when convenient. No gameplay/input behavior changed. No
**Coach.app** rebuild is required for this command-line matrix update.
If explicit fields conflict with `gameplay=true`, the trial is rejected.

All deltas are fixed +/-2 or zero; no firing, aiming, automated sequences or
Head Lock. A trial needs a fresh key edge, quiet >=300 ms baseline, >=400 ms
pulse observation and >=400 ms post observation. Active axes must still exceed
0.005 degrees and remain below 3 degrees in the expected direction. Matrix
validation requires one nonzero Unity input frame; unused axes must stay quiet.
This is at least as strict as calibration, not a relaxed diagonal acceptance.

Focus, AX, destination owner/executable and emergency state are checked.
Focus/gameplay loss cancels any pending trial and returns to **WAITING_FOR_GAME**,
rather than terminating the diagnostic. Stability and quiet history are cleared.
F4/F6 pressed or held while waiting are consumed: release and press again after
READY. No event is queued, retried or sent during transitions. Missing/stale
telemetry, menus and pause also keep input blocked. A changed selected
window/PID/executable remains fatal; it is never silently retargeted.

Unexpected rotation, multiple-frame response, counter reset or noisy post-window
still aborts the run. A completely silent failed pulse is retained
for comparison and may be retried **only** by another fresh manual press with
another quiet baseline. No automatic retries occur.

JSONL output:
`~/Library/Logs/AI-Aim-Trainer/quartz_matrix/assist-<id>.jsonl`

Records include case/method, dynamic window/owner/executable, foreground PID,
AX trust, source PID/thread, event timestamp/delta readback, posting intervals,
baseline telemetry, per-frame-snapshot samples and Unity axes/raw sums and
camera rotation outcomes. Zero controls have no event timestamp. Snapshots are
not hardware timestamped; response provenance remains unproven.

To aggregate recorded outcomes without posting input:

```sh
.venv/bin/python -m coach_app.quartz_matrix --summarize "$HOME"/Library/Logs/AI-Aim-Trainer/quartz_matrix/*.jsonl
```

The summary retains failed/aborted trials and reports case/method pass counts,
silent failures, observed axes/rotation means and standard deviations, and
event timestamps. Inspect individual traces and process states before inferring
a cause. A timestamp-initialization change is not justified by the zero value
alone; a matched, explicitly authorized experiment would be needed to test it.

## Focus-transition exits and shutdown records

Reviewed latest log: `assist-c5c8cffb6d40407198b0e7f8eff62526.jsonl`, October 22
America/Toronto time:

- 21:09:09.852: foreground/selected PID 87953, fresh telemetry, but Unity
  `application_focused=false`, blocker `application_not_focused`. Cursor Locked,
  session active, paused=false, Settings/Summary closed.
- 21:09:11.796: foreground Terminal 64533; the latest Unity frame still reported
  gameplay=true. The file ends on `foreground_pid_mismatch`.

The old code set `engaged=true` after one valid sample, then returned False on
any subsequent failed precondition. That return breaks the main loop even if
there is no pending trial. This is a definite exit path matching the log tails.
The new waiting state replaces it without accepting any invalid condition.

Historical logs contain no hotkey/shutdown markers, so ESC/F8, Ctrl-C, signals
and exceptions cannot all be ruled out retrospectively. None was explicitly
recorded in that latest file. Its last row records a switch away from Unity,
not an observed stable arrival in Unity.

New records:

- `state_transition`: WAITING_FOR_GAME or READY, with reason/stability duration.
- `hotkey`: actual F4/F6/F8/ESC press/release with current control state.
- `hotkey_rejected`: waiting reason; no delayed input follows it.
- `matrix_shutdown`: final reason, last state/preconditions/hotkeys. Exceptions
  include type/message/traceback; catchable signals include their signal number.

F8/ESC terminate immediately even at the final native gate; they never become
recoverable focus rejections. SIGINT (normally Ctrl-C), SIGTERM and SIGHUP are
separately recorded. SIGKILL, native crashes or power loss may prevent a final
record; its absence is not proof of normal termination.

To verify without synthetic input, run `--case zero`, physically switch
Terminal -> Unity -> Terminal -> Unity, and wait for READY each time. F4/F6 in
this case are no-event controls. The process should survive focus transitions;
F8/ESC should produce an explicit shutdown record. No Coach.app rebuild is needed.
