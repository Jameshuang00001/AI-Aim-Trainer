# AI Aim Trainer

Unity aim trainer with a floating macOS Coach. Mode 1 provides session reports; Mode 2 uses Unity head hit zones, camera and game state for smooth, bounded assistance. Firing stays manual.

## Development

Open this folder with the Unity version recorded in `ProjectSettings/ProjectVersion.txt`. Keep `Assets` and its `.meta` files, `Packages`, and `ProjectSettings` together.

For Coach development, use a Tk-enabled Python 3.10+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r coach_app/requirements.txt
.venv/bin/python -m coach_app.main
.venv/bin/python -m unittest discover -s coach_app -p 'test_*.py'
```

See [Coach controls](coach_app/MODE2_SETUP.md) and [integration](coach_app/INTEGRATION.md). Coach's **API key** button accepts the user's own Nebius key in a masked input and saves it in that Mac's login Keychain. Cancel keeps the existing value. No key belongs in this repository or the release app. An explicitly configured `NEBIUS_API_KEY` environment variable takes precedence over Keychain.

## macOS packaging

Build Unity with `Mode2Build.Build`, then assemble a new destination:

```sh
.venv/bin/python -m pip install -r coach_app/requirements-build.txt
.venv/bin/python tools/package_macos.py /absolute/path/to/AI-Aim-Trainer.app
```

The output embeds Coach and its Python/GUI runtime. Copy the entire app. The current bundled Coach runtime targets Apple Silicon; Intel needs a separate runtime build. Packaging uses ad-hoc signing, without Apple notarization. Online AI advice requires the receiving user's key and network access. Local gameplay and measured statistics do not require an API key.

Generated apps/archives belong in release distribution, outside source control. Local sessions, credentials, datasets, weights, caches and retired visual-assist experiments are excluded. Existing game assets are retained to preserve scene references.
