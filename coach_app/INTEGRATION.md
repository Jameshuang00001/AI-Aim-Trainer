# Unity / Coach integration

Unity launches the Coach companion and communicates over loopback port 8765 with a per-launch token. Packaged games prefer `Contents/Helpers/Coach.app`; Editor development can use the project Python environment. The owned companion closes when the game exits.

Unity owns targeting, input gates and camera rotation. Coach sends assistance mode, zone, speed and Start/Stop commands. Its authenticated heartbeat reports game state and corrections; remote control expires without renewal. A health check using `/health?startup=1` does not look up credentials.

Session JSON is exported through the existing session pipeline. Coach computes measured statistics locally, then optionally sends the measurements and supported exercise choices to Nebius. API credentials come from an explicit environment variable first, then macOS Keychain; credentials are never part of session JSON or application packaging.

See [controls](MODE2_SETUP.md), [project setup](../README.md) and `tools/package_macos.py` for development and distribution.
