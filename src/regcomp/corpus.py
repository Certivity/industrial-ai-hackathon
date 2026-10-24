"""Where the regulation PDFs are: regulations/index.json, and the files fetched into regulations/data/<regulation>/<role>/.

    python tools/fetch_regulations.py --out regulations/data      # downloads them (the folder layout is the tool's)
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "regulations" / "index.json"
DATA = ROOT / "regulations" / "data"


def slug(regulation: str) -> str:
    """'UN R150' -> 'UN_R150', the folder name tools/fetch_regulations.py uses."""
    return "_".join(regulation.replace("/", " ").split())


def load_index() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def entry_for(regulation: str) -> dict:
    for entry in load_index():
        if entry["regulation"] == regulation:
            return entry
    raise KeyError(f"{regulation} is not in {INDEX.name}")


def version_of(entry: dict, role: str) -> dict | None:
    """The 'base' or 'latest' version of an index entry, or None if the regulation has no such version."""
    return next((v for v in entry.get("versions", []) if v.get("role") == role), None)


def version_label(entry: dict, role: str = "base") -> str | None:
    version = version_of(entry, role)
    return version["version_label"] if version else None


def pdf_path(entry: dict, role: str = "base") -> Path | None:
    """Local path of the version's PDF, or None if the version does not exist or has not been fetched."""
    version = version_of(entry, role)
    if not version or not version.get("files"):
        return None
    path = DATA / slug(entry["regulation"]) / role / version["files"][0]["name"]
    return path if path.is_file() else None


def all_pdfs() -> list[tuple[str, str, Path]]:
    """(regulation, role, path) for every fetched PDF, in index order."""
    found = []
    for entry in load_index():
        for role in ("base", "latest"):
            path = pdf_path(entry, role)
            if path is not None:
                found.append((entry["regulation"], role, path))
    return found
