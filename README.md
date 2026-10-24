# webfonts

Webfonts split into unicode-range woff2 subsets and served from this repository through jsDelivr.

## Fonts

| Font | Branch | Upstream |
| --- | --- | --- |
| Maple Mono NL NF CN 7.9 | `font/maple-mono-nl-nf-cn` | [subframe7536/maple-font v7.9](https://github.com/subframe7536/maple-font/releases/tag/v7.9) |

Each font has its own orphan branch that holds only the generated CSS, the woff2 subsets and the font's license, so jsDelivr's 150 MB package limit applies to one font at a time. Releases are tags on that branch named `<font>-v<version>`, for example `maple-mono-nl-nf-cn-v1.0.0`. A page loads one weight and style like this:

```
https://cdn.jsdelivr.net/gh/RottenSea/webfonts@<tag>/<upstream version>/<weight>-<style>/result.css
```

## How fonts are split

Subsets follow Google Fonts. The [googlefonts/nam-files](https://github.com/googlefonts/nam-files) submodule in `vendor/nam-files`, pinned to release `v2025.11.04`, supplies the `latin` and `latin-ext` subsets and the Simplified Chinese slicing strategy. A font's codepoints go into those subsets first, Latin before the Chinese slices. Codepoints that none of them lists, such as Nerd Font icons and rarer han, are grouped by Unicode block: a large block is cut into groups of about 50 KB of raw glyph data, and neighbouring small blocks share a group up to that size.

[fontTools](https://github.com/fonttools/fonttools) cuts each group into a woff2 file named by a hash of its content. `result.css` has one `@font-face` per file. The same source font always gives the same files, so a rebuild with no font change leaves nothing to commit.

## Building

You need [uv](https://docs.astral.sh/uv/).

1. Clone with submodules: `git clone --recurse-submodules https://github.com/RottenSea/webfonts.git`. In an existing clone, run `git submodule update --init`.
2. Run `uv sync` to install the pinned fontTools and brotli from `uv.lock`.
3. Download the upstream fonts as described in [`source/README.md`](source/README.md).
4. Check out the font's branch under `dist/`: `git worktree add dist/maple-mono-nl-nf-cn font/maple-mono-nl-nf-cn`.
5. Preview the grouping with `uv run scripts/split.py maple-mono-nl-nf-cn --dry-run`.
6. Run `uv run scripts/split.py maple-mono-nl-nf-cn [<weight>-<style> ...]`. Without styles it builds every style listed for that font in `fonts.json`.
7. Commit and tag inside the worktree, then push the branch and the tag.

To move to a newer nam-files release, check out its tag in `vendor/nam-files`, commit the submodule, and rebuild.

## License

The scripts are under the Apache License 2.0 in `LICENSE`. Google's subset data in `vendor/nam-files` is also under Apache 2.0. Each font keeps its own license, shipped as `OFL.txt` on its branch.
