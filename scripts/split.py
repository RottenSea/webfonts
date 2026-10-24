"""Split a font from fonts.json into unicode-range woff2 subsets.

Usage: uv run scripts/split.py <font-id> [<weight>-<style> ...] [--dry-run]

Subsets follow Google Fonts: its latin and latin-ext subsets first, then its
Simplified Chinese slices with those Latin codepoints taken out, all read from
the vendor/nam-files submodule.
"""

import argparse
import json
import re
from pathlib import Path

from fontTools.ttLib import TTFont

NAM_FILES = Path("vendor/nam-files")
LATIN_SUBSETS = ["latin", "latin-ext"]
CJK_SLICES = NAM_FILES / "slices/simplified-chinese_default.txt"


def load_subset(name: str) -> set[int]:
    """Codepoints of a Google Fonts subset, one 0x-prefixed codepoint per line."""
    text = (NAM_FILES / f"Lib/gfsubsets/data/{name}_unique-glyphs.nam").read_text(encoding="utf-8")
    return {int(cp, 16) for cp in re.findall(r"^0x([0-9A-Fa-f]+)", text, re.M)}


def load_slices() -> list[set[int]]:
    """Google's slices, highest priority (most frequent characters) first.

    The text proto lists them lowest priority first: its header's priority 1
    is the last subsets block.
    """
    text = CJK_SLICES.read_text(encoding="utf-8")
    blocks = [set(map(int, re.findall(r"codepoints:\s*(\d+)", b))) for b in text.split("subsets {")[1:]]
    return blocks[::-1]


def google_groups(available: set[int]) -> list[tuple[str, set[int]]]:
    """Google's subsets cut down to what the font has, each codepoint in one group only."""
    groups, taken = [], set()
    # Google Fonts serves Latin from these subsets and also scatters ASCII
    # through low-priority Chinese slices. Taking Latin out first keeps a
    # Latin-only page to one small file.
    for name in LATIN_SUBSETS:
        group = (load_subset(name) & available) - taken
        if group:
            groups.append((name, group))
            taken |= group
    for i, s in enumerate(load_slices(), start=1):
        group = (s & available) - taken
        if group:
            groups.append((f"chinese-simplified-{i}", group))
            taken |= group
    return groups


def plan(font: dict, style: str) -> list[tuple[str, set[int]]]:
    path = Path(font["source"]) / font["styles"][style]["file"]
    if not path.exists():
        raise SystemExit(f"Missing {path}. See source/README.md.")
    available = set(TTFont(path, lazy=True).getBestCmap())
    groups = google_groups(available)
    covered = set().union(*(g for _, g in groups))
    print(f"{style}: {len(available)} codepoints in the font")
    print(f"  {len(groups)} Google groups cover {len(covered)}")
    print(f"  {len(available - covered)} codepoints left over")
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("font")
    parser.add_argument("styles", nargs="*")
    parser.add_argument("--dry-run", action="store_true", help="print the grouping without writing files")
    args = parser.parse_args()

    fonts = json.loads(Path("fonts.json").read_text(encoding="utf-8"))
    if args.font not in fonts:
        raise SystemExit(f"Unknown font {args.font!r}. Known: {', '.join(fonts)}")
    font = fonts[args.font]
    for style in args.styles or font["styles"]:
        plan(font, style)
    if not args.dry_run:
        raise SystemExit("Only --dry-run is implemented so far.")


if __name__ == "__main__":
    main()
