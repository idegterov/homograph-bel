# Notices

## Belarus GrammarDB data

The bundled Dictionary v2 is adapted from **Belarus GrammarDB**, release
`RELEASE-202601`, published by the Belarus project:

- Project: https://github.com/Belarus/GrammarDB
- Release: https://github.com/Belarus/GrammarDB/releases/tag/RELEASE-202601
- Source archive: `RELEASE-202601.zip`
- Source archive SHA-256:
  `393756f3cb5c94ab86cdbd64b95fa9d096775f559ae65de6375ebb6d5571df00`
- Pinned source commit:
  `c328ce92bfe43479277fd02ecc4448d223990918`
- Upstream license: CC BY-SA 4.0

Changes made by this project:

- selected the official 2008 Belarusian orthography (`A2008`);
- parsed the pinned XML members into normalized source analyses;
- grouped unstressed surface forms having multiple stress positions;
- emitted linked `homographs`, `candidates`, and `analyses` JSONL tables;
- assigned deterministic identifiers and retained source coordinates;
- attached lifecycle/status metadata and a versioned morphology decoder;
- removed build and QA reports from the redistribution archive; and
- repackaged the four public contract files as a portable tar.gz resource.

Derived database release: `RELEASE-202601`

Dictionary logical SHA-256:
`c0b5ddedb74bc0bf22e9a538c0ca0eafa076d8bbc7411422a174ffb89e92fc27`

Bundled tar.gz SHA-256:
`ed69710bf1bb9b57ec83eb17ca220485749a45e5e636c117ab543addd3f95390`

The derived database is distributed under CC BY-SA 4.0. See
`DATA_LICENSE.md` and `LICENSES/CC-BY-SA-4.0.txt`.

## Grammar tag interpretation

The morphology decoder is versioned `grammardb-unimorph-c328ce92`. Its tag
interpretation is pinned to the same GrammarDB source revision. The application
code containing that decoder is distributed under GPL-3.0-or-later.
