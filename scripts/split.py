"""Split a font from fonts.json into unicode-range woff2 subsets.

Usage: uv run scripts/split.py <font-id> [<weight>-<style> ...] [--dry-run]

Subsets follow Google Fonts: its latin and latin-ext subsets first, then its
Simplified Chinese slices with those Latin codepoints taken out, all read from
the vendor/nam-files submodule. Codepoints none of them lists are grouped by
Unicode block: a large block is cut into groups of about --group-kb of raw
glyph data, and neighbouring small blocks share a group up to that size.
"""

import argparse
import json
import re
from pathlib import Path

from fontTools import unicodedata
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


class Sizer:
    """Raw glyph data a set of codepoints pulls in, counting each glyph once."""

    def __init__(self, font: TTFont):
        self.cmap = font.getBestCmap()
        self.glyf = font["glyf"]
        self.cache: dict[str, int] = {}

    def glyph(self, cp: int) -> str:
        return self.cmap[cp]

    def bytes(self, glyph: str) -> int:
        if glyph not in self.cache:
            g = self.glyf[glyph]
            self.cache[glyph] = len(g.compile(self.glyf)) if g.numberOfContours else 0
        return self.cache[glyph]

    def total(self, cps) -> int:
        return sum(self.bytes(g) for g in {self.glyph(cp) for cp in cps})


def cut(cps: list[int], sizer: Sizer, cap: int) -> list[set[int]]:
    """Cut codepoints, in order, into groups of about cap bytes."""
    groups, current, seen, size = [], set(), set(), 0
    for cp in cps:
        glyph = sizer.glyph(cp)
        if glyph not in seen:
            seen.add(glyph)
            size += sizer.bytes(glyph)
        current.add(cp)
        if size >= cap:
            groups.append(current)
            current, seen, size = set(), set(), 0
    return groups + ([current] if current else [])


def leftover_groups(leftovers: set[int], sizer: Sizer, cap: int) -> list[tuple[str, set[int]]]:
    blocks: dict[str, list[int]] = {}
    for cp in sorted(leftovers):
        blocks.setdefault(unicodedata.block(chr(cp)), []).append(cp)

    groups: list[tuple[list[str], set[int]]] = []
    pending: tuple[list[str], set[int]] = ([], set())
    for block, cps in blocks.items():  # dicts keep insertion order, so this is codepoint order
        size = sizer.total(cps)
        if size >= cap:
            # A large block never shares a group with its neighbours.
            if pending[1]:
                groups.append(pending)
                pending = ([], set())
            groups += [([block], g) for g in cut(cps, sizer, cap)]
        elif pending[1] and sizer.total(pending[1] | set(cps)) > cap:
            groups.append(pending)
            pending = ([block], set(cps))
        else:
            pending = (pending[0] + [block], pending[1] | set(cps))
    if pending[1]:
        groups.append(pending)

    named, counts = [], {}
    for blocks_in_group, cps in groups:
        slug = re.sub(r"[^a-z0-9]+", "-", blocks_in_group[0].lower()).strip("-")
        if len(blocks_in_group) > 1:
            slug += f"-and-{len(blocks_in_group) - 1}-more"
        counts[slug] = counts.get(slug, 0) + 1
        named.append((f"{slug}-{counts[slug]}", cps, blocks_in_group))
    return named


def plan(font: dict, style: str, cap: int) -> list[tuple[str, set[int]]]:
    path = Path(font["source"]) / font["styles"][style]["file"]
    if not path.exists():
        raise SystemExit(f"Missing {path}. See source/README.md.")
    ttf = TTFont(path)
    sizer = Sizer(ttf)
    available = set(sizer.cmap)
    google = google_groups(available)
    leftovers = available - set().union(*(g for _, g in google))
    own = leftover_groups(leftovers, sizer, cap)

    print(f"{style}: {len(available)} codepoints in the font")
    print(f"  {len(google)} Google groups cover {len(available) - len(leftovers)}")
    print(f"  {len(own)} own groups cover the other {len(leftovers)}")
    print(f"\n  {'group':52} {'codepoints':>10} {'raw KB':>7}  blocks")
    for name, cps, blocks in own:
        print(f"  {name:52} {len(cps):10} {sizer.total(cps) / 1024:7.1f}  {', '.join(blocks)}")
    return google + [(name, cps) for name, cps, _ in own]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("font")
    parser.add_argument("styles", nargs="*")
    parser.add_argument("--dry-run", action="store_true", help="print the grouping without writing files")
    parser.add_argument("--group-kb", type=int, default=50, help="raw glyph data per own group")
    args = parser.parse_args()

    fonts = json.loads(Path("fonts.json").read_text(encoding="utf-8"))
    if args.font not in fonts:
        raise SystemExit(f"Unknown font {args.font!r}. Known: {', '.join(fonts)}")
    font = fonts[args.font]
    for style in args.styles or font["styles"]:
        plan(font, style, args.group_kb * 1024)
    if not args.dry_run:
        raise SystemExit("Only --dry-run is implemented so far.")


if __name__ == "__main__":
    main()
