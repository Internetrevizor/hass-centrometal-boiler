"""The script the release workflow uses to take the notes from CHANGELOG.md."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release_notes", ROOT / ".github" / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## 1.2.0 — newer

- New thing.

## 1.1.0 — features from the other forks

- Feature one.
- Feature two.

## 1.1 — not this one

- Old.
"""


def test_takes_exactly_one_section() -> None:
    notes = release_notes.section(CHANGELOG, "1.1.0")
    assert notes.startswith("## 1.1.0 — features from the other forks\n")
    assert "- Feature two." in notes
    assert "1.2.0" not in notes
    assert "Old." not in notes


def test_version_prefix_does_not_match_a_longer_version() -> None:
    assert "Old." in release_notes.section(CHANGELOG, "1.1")
    assert "Feature one." not in release_notes.section(CHANGELOG, "1.1")


def test_missing_version_is_an_error() -> None:
    with pytest.raises(LookupError):
        release_notes.section(CHANGELOG, "9.9.9")


def test_the_current_version_has_release_notes() -> None:
    """A version bump without a changelog section would fail the release."""
    import json

    manifest = json.loads((ROOT / "custom_components/centrometal_boiler/manifest.json").read_text())
    notes = release_notes.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), manifest["version"])
    assert notes.startswith(f"## {manifest['version']}")
