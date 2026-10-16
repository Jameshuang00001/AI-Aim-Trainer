"""Environment-first credentials with an explicit macOS Keychain backend."""

import argparse
import getpass
import os
import sys
import warnings

SERVICE = "AI Aim Trainer Coach"
ACCOUNT = "NEBIUS_API_KEY"
MISSING_KEY_MESSAGE = (
    "NEBIUS_API_KEY is not set and no macOS Keychain key is available. "
    "Run .venv/bin/python -m coach_app.credentials setup from the project folder."
)


class CredentialError(RuntimeError):
    """Only safe messages; never include backend exceptions or secret values."""


def macos_backend():
    if sys.platform != "darwin":
        raise CredentialError("macOS Keychain is unavailable on this platform. Set NEBIUS_API_KEY in the environment.")
    try:
        # Explicit backend prevents selecting a plaintext or third-party key store.
        from keyring.backends.macOS import Keyring
        return Keyring()
    except Exception:
        raise CredentialError("macOS Keychain support is unavailable. Install coach_app/requirements.txt in .venv.") from None


def get_api_key() -> str | None:
    key = os.environ.get(ACCOUNT, "").strip()
    if key:
        return key
    if sys.platform != "darwin":
        return None
    try:
        key = macos_backend().get_password(SERVICE, ACCOUNT)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("Cannot access the Nebius key in macOS Keychain. Unlock your login Keychain and allow access for the project's Python, then retry.") from None
    return key.strip() if key and key.strip() else None


def credential_status() -> tuple[bool, str]:
    try:
        return bool(get_api_key()), ""
    except CredentialError as error:
        return False, str(error)


def save_api_key(key: str) -> None:
    if not key.strip():
        raise CredentialError("The API key cannot be empty.")
    try:
        macos_backend().set_password(SERVICE, ACCOUNT, key.strip())
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("Could not save the key to macOS Keychain. Unlock your login Keychain and allow access, then retry.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Store the Nebius API key securely in macOS Keychain")
    parser.add_argument("command", choices=["setup"])
    parser.parse_args()
    try:
        if not sys.stdin.isatty():
            raise CredentialError("Run setup in an interactive Terminal so the key can be entered without echo.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Nebius API key (hidden): ")
        save_api_key(key)
        print("Nebius key saved in macOS Keychain. No key was written to project files.")
        return 0
    except (CredentialError, getpass.GetPassWarning) as error:
        print(str(error) if isinstance(error, CredentialError) else "A hidden prompt is unavailable; setup cancelled.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Keychain setup cancelled.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
