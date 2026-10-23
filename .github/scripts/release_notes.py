"""Print the CHANGELOG.md section for one version, for the release notes.

Usage: release_notes.py VERSION [CHANGELOG]

Exits with an error when the changelog has no section for the version, so a
release can never go out without its notes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def section(changelog: str, version: str) -> str:
    """Return the "## <version> ..." section, heading included, without the next one."""
    heading = re.compile(rf"^## {re.escape(version)}(?:\s|$)")
    lines = changelog.splitlines()
    start = next((i for i, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        raise LookupError(f"CHANGELOG.md has no section for {version}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[1]
    path = Path(argv[2]) if len(argv) == 3 else Path("CHANGELOG.md")
    try:
        sys.stdout.write(section(path.read_text(encoding="utf-8"), version))
    except LookupError as err:
        print(f"::error::{err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
