#!/usr/bin/env python3
"""Repair known syntax damage in the MoviePilot frontend release."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def patch_index(path: Path) -> bool:
    if not path.is_file():
        return False

    text = path.read_text(encoding="utf-8")
    original = text

    # A malformed generated comment can swallow the following const declaration.
    for marker in (
        "const launchThemePalettes = {",
        "if ('caches' in window) {",
        "function syncThemeFavicon(primaryColor) {",
        "revealOriginalLoadingLogo()",
        "const storedLoaderColor =",
        "function syncInitialViewport(force) {",
    ):
        text = re.sub(
            rf"(?m)^([ \t]*//[^\r\n]*?)([ \t]+{re.escape(marker)}[^\r\n]*)$",
            r"\1\n\2",
            text,
        )

    # The same generated HTML occasionally appends a closing brace to a
    # localized comment instead of emitting a line break.
    text = re.sub(r"(?m)^([ \t]*//[^\r\n]*?)([ \t]+\})$", r"\1\n\2", text)

    # One localized VersionChecker message in the upstream HTML is missing its
    # closing quote. Keep this narrow so valid JavaScript is not reformatted.
    text = re.sub(
        r"(?m)^([ \t]*console\.log\('\[VersionChecker\].*?)(?<!')\)$",
        r"\1')",
        text,
    )
    text = re.sub(r"(?m)^([ \t]*text:[ \t]*'[^'\r\n]*)(,)$", r"\1'\2", text)

    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-frontend.py <frontend-index.html>")
    changed = patch_index(Path(sys.argv[1]))
    print(f"frontend index {'patched' if changed else 'already clean'}: {sys.argv[1]}")
