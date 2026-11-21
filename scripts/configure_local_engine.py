"""Create a local, git-ignored engine signing key without modifying user .env."""
from pathlib import Path
import secrets


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    key = root / ".run" / "engine-jwt.key"
    key.parent.mkdir(exist_ok=True)
    if not key.exists():
        with key.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
    print("Local engine signing key ready; value not displayed.")
