"""Split a font from fonts.json into unicode-range woff2 subsets.

Usage: uv run scripts/split.py <font-id> [<weight>-<style> ...] [--dry-run]

Subsets follow Google Fonts: its latin and latin-ext subsets first, then its
Simplified Chinese slices with those Latin codepoints taken out, all read from
the vendor/nam-files submodule. Codepoints none of them lists are grouped by
Unicode block: a large block is cut into groups of about --group-kb of raw
glyph data, and neighbouring small blocks share a group up to that size.

Output goes to dist/<font-id>/<version>/<weight>-<style>/, the worktree of
branch font/<font-id>: one woff2 per group, named by a hash of its content,
and a result.css with one @font-face per group.
"""

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import fontTools
from fontTools import subset, unicodedata
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


def plan(font: dict, style: str, cap: int, verbose: bool) -> list[tuple[str, set[int]]]:
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
    if verbose:
        print(f"\n  {'group':52} {'codepoints':>10} {'raw KB':>7}  blocks")
        for name, cps, blocks in own:
            print(f"  {name:52} {len(cps):10} {sizer.total(cps) / 1024:7.1f}  {', '.join(blocks)}")
    return google + [(name, cps) for name, cps, _ in own]


_font_bytes = b""


def init_worker(font_bytes: bytes) -> None:
    global _font_bytes
    _font_bytes = font_bytes


def subset_woff2(cps: list[int]) -> bytes:
    # recalcTimestamp=False keeps head.modified from the source font, so the
    # same input always gives the same bytes.
    font = TTFont(io.BytesIO(_font_bytes), recalcTimestamp=False)
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    # fontTools cannot subset the meta table and would drop it with a warning.
    options.drop_tables += ["meta"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=cps)
    subsetter.subset(font)
    # Options.flavor only applies in the pyftsubset CLI; the API reads it from the font.
    font.flavor = "woff2"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def unicode_range(cps: set[int]) -> str:
    ordered, parts, i = sorted(cps), [], 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[j] + 1:
            j += 1
        parts.append(f"U+{ordered[i]:X}" if i == j else f"U+{ordered[i]:X}-{ordered[j]:X}")
        i = j + 1
    return ",".join(parts)


def css_header(ttf: TTFont) -> str:
    name = ttf["name"]
    lines = [name.getDebugName(i) for i in (0, 5, 13, 14)]  # copyright, version, license, license URL
    nam_version = subprocess.run(
        ["git", "-C", str(NAM_FILES), "describe", "--tags", "--always"], capture_output=True, text=True, check=True
    ).stdout.strip()
    lines.append(f"Subsets follow Google Fonts' latin, latin-ext and Simplified Chinese slices (nam-files {nam_version}).")
    lines.append(f"Split with fontTools {fontTools.version}.")
    return "/*\n" + "".join(f" * {line}\n" for line in lines if line) + " */\n"


def write_style(font_id: str, font: dict, style: str, groups: list[tuple[str, set[int]]]) -> None:
    spec = font["styles"][style]
    font_bytes = (Path(font["source"]) / spec["file"]).read_bytes()
    out_dir = Path("dist", font_id, font["version"], style)
    # File names are content hashes, so clear the folder instead of leaving stale files.
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    with ProcessPoolExecutor(initializer=init_worker, initargs=(font_bytes,)) as pool:
        blobs = list(pool.map(subset_woff2, [sorted(cps) for _, cps in groups]))

    weight, font_style = style.split("-")
    local = ",".join(f'local("{n}")' for n in spec["local"])
    faces = []
    for (_, cps), blob in zip(groups, blobs):
        file = hashlib.sha256(blob).hexdigest()[:16] + ".woff2"
        (out_dir / file).write_bytes(blob)
        faces.append(
            f'@font-face{{font-family:"{font["family"]}";src:{local},url("./{file}")format("woff2");'
            f"font-style:{font_style};font-weight:{weight};font-display:swap;"
            f"unicode-range:{unicode_range(cps)}}}\n"
        )
    header = css_header(TTFont(io.BytesIO(font_bytes), lazy=True))
    (out_dir / "result.css").write_text(header + "".join(faces), encoding="utf-8", newline="\n")
    total = sum(len(b) for b in blobs)
    print(f"  wrote {len(blobs)} woff2 files ({total / 1048576:.1f} MB) and result.css to {out_dir}")


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
    root = Path("dist", args.font)
    if not args.dry_run:
        if not root.exists():
            raise SystemExit(f"Missing {root}. Check out its branch: git worktree add {root} font/{args.font}")
        shutil.copyfile(Path(font["source"]) / font["license"], root / "OFL.txt")
    for style in args.styles or font["styles"]:
        groups = plan(font, style, args.group_kb * 1024, verbose=args.dry_run)
        if not args.dry_run:
            write_style(args.font, font, style, groups)


if __name__ == "__main__":
    main()
