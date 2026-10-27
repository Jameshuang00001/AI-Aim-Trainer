# AI Aim Trainer — Original / Full Project

## Two editions

| Edition | Purpose | Source | macOS download |
| --- | --- | --- | --- |
| **Original / Full Project** | The creator's complete original project and visual presentation | [main](https://github.com/Jameshuang00001/AI-Aim-Trainer/tree/main) | [Original v1.0.1](https://github.com/Jameshuang00001/AI-Aim-Trainer/releases/tag/v1.0.1) |
| **Hackathon Submission Edition** | A separate competition build with project-authored primitive scenery, targets, mechanical arms and gun | [competition-submission](https://github.com/Jameshuang00001/AI-Aim-Trainer/tree/competition-submission) | [Competition v1.0.0](https://github.com/Jameshuang00001/AI-Aim-Trainer/releases/tag/competition-v1.0.0) |

The competition edition is a presentation/artwork variant, not a replacement for the full original project. It keeps the same gameplay and Coach runtime code. It uses a light training range, blue geometric targets and a simple blaster in place of the imported environment, character/animations and arms/gun. Both editions remain available separately. Run one edition at a time; they use the same local Coach port.


A Unity aim trainer with a floating desktop Coach that connects measured practice sessions to NVIDIA Nemotron through Nebius Token Factory.

**Train → measure → select a supported drill → practice again.**

- [Download the original macOS app](https://github.com/Jameshuang00001/AI-Aim-Trainer/releases/tag/v1.0.1)
- [Source repository](https://github.com/Jameshuang00001/AI-Aim-Trainer)
- Suggested hackathon track: **Best Apps and Agents**

## What it does

AI Aim Trainer combines a first-person shooting range with a Coach window. Players can practice manually, inspect session results, and request a next exercise. An optional assistance mode records the gap that the helper closes, making assisted alignment visible without treating it as proof of improved manual skill.

The game includes Static, Moving, Flick and Reaction target modes, adjustable mouse sensitivity, session controls, and a Settings panel that scales with the game window.

Coach offers:

- **Mode 1 — session coaching:** measured session summaries and an optional model-selected next drill.
- **Mode 2 — Unity assistance:** either Hold RMB or Proximity magnet, controlled from Coach with adjustable assistance speed and angular zone.

In proximity mode, an eligible head must be inside the configured zone and mouse input must remain still for 150 ms before assistance starts. Moving the mouse interrupts this assistance. Hold RMB assistance stops on release. Camera rotation is smooth and bounded; firing remains manual. Stop, F8 and Escape stop assistance, and game-state/focus checks gate its operation.

## What NVIDIA and Nebius do

| Component | Actual responsibility |
| --- | --- |
| Unity / C# | Game simulation, head hit zones, target visibility checks, camera control, manual firing and measurement collection |
| Local Python Coach | Session summaries, explanations of what measurements mean, eligible exercise definitions and validation of model output |
| NVIDIA Nemotron | Reads the prepared session measurements and eligible drills, then selects a drill identifier |
| Nebius Token Factory | Hosts the NVIDIA model inference used by Coach at runtime |

The inference endpoint is `https://api.tokenfactory.nebius.com/v1/`. Coach checks the account's model catalog and selects the first available model in this configured order:

1. `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
2. `nvidia/Nemotron-3_5-Lightning`
3. `nvidia/nemotron-3-super-120b-a12b`

Model availability depends on the account and service catalog. If none is available, Coach reports the error and retains a local measured report.

The client uses the OpenAI Python SDK as an API-compatible client; requests go to **Nebius**, not to an OpenAI-hosted model. There is no custom model training or fine-tuning, and the game is not hosted on Nebius AI Cloud. Token Factory provides hosted inference so the desktop app does not need a local LLM runtime or a separately managed model server. No latency, cost or gameplay-improvement benchmark is claimed.

## How an online coaching request works

1. Unity exports session JSON, including shots, hits, misses, timing and optional `aim_corrections` records.
2. Coach prepares measurements and defines the drills supported by that session's evidence.
3. Coach sends the prepared measurements and drill choices to Nemotron through Token Factory. The input can include per-shot and assistance details, not only aggregate statistics.
4. The requested response is a JSON object containing only `drill_id`.
5. Code checks the response schema and whether the selected drill is eligible. An invalid or truncated selection is retried once; repeated invalid output falls back to a local report. Connection/authentication failures also preserve local measured feedback with an error message.
6. Coach renders locally defined instructions and measured explanations. Free-form model claims are not displayed as measured facts.

**The model does not control the camera or fire shots.** The proximity and RMB helpers are Unity algorithms. Nemotron's role is constrained exercise selection, rather than unrestricted diagnosis or autonomous gameplay.

## Interpreting the measurements

Coach summarizes all recorded assistance segments in the session, including mean entry gap, applied angular path and remaining gap. The remaining gap is sampled when a segment ends, not at the shot. The displayed reaction metric includes target acquisition and aiming time; it is not a clinical reaction-time measurement.

Assisted accuracy is labeled as assisted. These measurements do not establish improved manual skill, diagnose why a miss occurred, or prove that a user overshoots or undershoots. Manual sessions can provide a separate comparison, but assistance-error records are not produced while assistance is off.

## Run the macOS release

1. Use an **Apple Silicon (M-series) Mac** and download the AppleSilicon ZIP from the edition-specific Release, rather than the automatically generated source archive.
2. Extract and keep the entire `AI-Aim-Trainer.app` together. Coach, Python and GUI runtime libraries are included; Unity Editor and a project checkout are not required.
3. Open the game. The floating Coach companion should launch with it.
4. For online coaching, click **API key** in Coach and enter your own Nebius API key. The masked entry saves to that Mac's login Keychain; Cancel keeps the existing value. An explicit `NEBIUS_API_KEY` environment variable takes precedence.
5. Start a session, take manual shots, and end it through the game's session controls. Review the Coach report; Open session and Latest session can also load exported session JSON.
6. For optional Mode 2 testing, choose an assistance type in Coach, press Start Assist, and confirm Stop / F8 / Escape stops assistance.

The release uses ad-hoc signing and is **not Apple-notarized**. macOS may block a downloaded copy with an “Apple could not verify” message; this is not a zero-friction distribution build. The current bundle does not support Intel Macs and has not been tested on a second Mac.

Offline gameplay and local measured reports do not need an API key. Online inference needs network access and a valid user-owned Nebius account/key, and may consume that account's credits. A credential-free judging arrangement has not yet been provided; neither edition should be represented as offering free hosted AI access to judges.

## Privacy and credentials

The release and repository contain no developer API key. Entered keys are stored outside the app in macOS Keychain. They are not written into session exports or included in release archives. The app does not require screen recording, YOLO, Quartz input injection or Accessibility permission.

For online analysis, session measurements are transmitted to Nebius. Do not load a JSON file containing information you do not want included in that analysis. This project does not claim that online coaching data stays entirely on the Mac.

## Develop from source

Use Unity **2022.3.35f1**, as recorded in `ProjectSettings/ProjectVersion.txt`. Open the repository root in Unity and use `Assets/Scenes/SampleScene.unity`. Preserve `Assets` and its `.meta` files, `Packages`, and `ProjectSettings` together.

For the Coach, use a Tk-enabled Python 3.10+ installation. On macOS, a Python distribution with Tk support is required; Tkinter is not installed through pip.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r coach_app/requirements.txt
.venv/bin/python -m coach_app.main
```

Coach and Unity communicate over loopback port 8765 using a per-launch token. Packaged games use their embedded Coach; Editor development can use the project's Python environment. The game's owned companion closes when the game exits.

### Tests

```sh
.venv/bin/python -m unittest discover -s coach_app -p 'test_*.py'
```

The final-source test snapshot passed 35 tests. Credential and inference tests use mocks; this is not evidence of a live paid inference request. Unity's build helper also checks assistance stop/rearm behavior, quiet-mouse gating, target-zone eligibility and occlusion.

### Build a portable macOS app

Build Unity by running the Editor method `Mode2Build.Build` with a valid Unity license. This generates `build/Mode2/AI-Aim-Trainer.app`. Then run:

```sh
.venv/bin/python -m pip install -r coach_app/requirements-build.txt
.venv/bin/python tools/package_macos.py /absolute/path/to/new/AI-Aim-Trainer.app
```

Choose a destination that does not already exist. Packaging embeds Coach and its runtime and checks for external symbolic links. Apple Developer ID signing/notarization is a separate distribution step. The v1.0.1 downloadable app additionally contains the supplied multi-resolution macOS icon; it reuses the tested game binary rather than a new Unity compilation.

## Work completed during the hackathon period

The Unity project began before August 26, 2026. During the submission period it gained the Nebius/NVIDIA coaching integration and was substantially updated with Unity-data-based assistance, proximity gating on mouse stillness, session-wide correction measurements, locally generated explanations, validated model drill selection, responsive Settings, a bundled macOS Coach runtime and per-user API key setup. The final submission does not depend on the retired visual-capture experiments.

## Project layout

- `Assets/` — Unity game, scenes and resources
- `Packages/`, `ProjectSettings/` — Unity dependencies and configuration
- `coach_app/` — desktop Coach, inference client, report logic and tests
- `tools/package_macos.py` — portable package assembly

See [Coach controls](coach_app/MODE2_SETUP.md) and [integration notes](coach_app/INTEGRATION.md).

## License and third-party assets

Project code is covered by the root [MIT License](LICENSE). Third-party models, animations, textures and dependencies retain their original licenses; the project's MIT file does not relicense them. A local provenance audit identified the original environment, character/animations and arms as third-party resources. Public raw-asset redistribution and AI-related license conditions are not cleared by this code license. The separate competition edition removes these imported resources from its current source tree and scene dependencies. It does not rewrite earlier public commits or remove earlier release archives.
