"""Download the reviewed ARCHITECT prompt and reference files for a Keme build."""

from hashlib import sha1
from pathlib import Path
from urllib.request import urlopen

REVISION = "6d21df5c7bc9cc41b2c7bd65693a8288aa6008b9"
SOURCE = f"https://raw.githubusercontent.com/Bigfigboy/ARCHITECT-AI-Systems-Business-Analyst/{REVISION}"
MATERIALS = {
    "system_prompt.md": "d09bd51e08019dd3815ec7de8171fb139a208fd6",
    "knowledge/01_requirements_checklist.md": "58bb8dce397d6b4da3233c1c6f3db9d3efee0397",
    "knowledge/02_ambiguity_dictionary.md": "ab487f689cf69623d594b28c5ba124583207e5cc",
    "knowledge/03_user_story_templates.md": "ed924a605514c589a26690c78e6df8f8b38a62d9",
    "knowledge/04_document_structures.md": "1d7710e9566486ebd05384a665ad549e59f7b098",
}


def main():
    root = Path(__file__).resolve().parents[1] / ".run" / "architect"
    for name, expected in MATERIALS.items():
        with urlopen(f"{SOURCE}/{name}", timeout=30) as response:
            data = response.read(65537)
        if len(data) > 65536 or sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != expected:
            raise RuntimeError(f"Unexpected ARCHITECT material: {name}")
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == "__main__":
    main()
