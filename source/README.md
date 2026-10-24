# Source fonts

Upstream font files are not committed. Download them into this folder before running the split script. Git ignores everything here except this README.

## Maple Mono NL NF CN 7.9

1. Download [`MapleMonoNL-NF-CN.zip`](https://github.com/subframe7536/maple-font/releases/download/v7.9/MapleMonoNL-NF-CN.zip) (159,320,985 bytes) from the [Maple Mono v7.9 release](https://github.com/subframe7536/maple-font/releases/tag/v7.9).
2. Check its SHA-256. It must be `6103d3a73d0095de6b34e709f3ecaf1147e35ab7717c03068e07c0bb0a8efa2e`, the same value as the release's `MapleMonoNL-NF-CN.sha256`.

   ```powershell
   Get-FileHash MapleMonoNL-NF-CN.zip -Algorithm SHA256
   ```

   ```bash
   sha256sum MapleMonoNL-NF-CN.zip
   ```

3. Extract it into a folder named `MapleMonoNL-NF-CN`, so this directory looks like this:

   ```
   source/
   ├─ README.md
   └─ MapleMonoNL-NF-CN/
      ├─ LICENSE.txt
      ├─ config.json
      ├─ MapleMonoNL-NF-CN-Regular.ttf
      ├─ MapleMonoNL-NF-CN-Italic.ttf
      ├─ ...
      └─ MapleMonoNL-NF-CN-ThinItalic.ttf
   ```

   The folder holds 16 TTF files: weights 100 to 800, each upright and italic. You can delete the zip afterwards.
