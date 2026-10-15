# Public Office corpus

This is an exploratory evaluation suite, separate from the small synthetic
regressions in `tests/fixtures/`. It currently contains 41 selected cases: 35
legacy Office files (including three encrypted inputs) and six modern controls.
Fixtures were selected by feature, not by whether Davros renders them well.
This small, deliberately chosen sample is not an estimate of real-world success.

`manifest.json` records upstream repository, full revision, path, size, SHA-256,
feature under investigation, and whether the input should render or be rejected.
The manifest and upstream license/notice texts are checked in; the downloaded
documents live in ignored `files/`. Source documents, reference PDFs, previews,
and the diagnostic executable are never included in the release bundle.
The upstream notices are preserved under `licenses/`; they are provenance, not
a claim that every embedded document asset has been independently audited.

## Reproduce

Build the normal runtime bundle first. The corpus additionally needs Linux,
Poppler, LibreOffice, and Bubblewrap. The runner uses only Python's standard
library. It does not require a Python LibreOffice bridge or Pillow.

```sh
./build.sh
cargo build --release --locked --example corpus-normalize -j 1
python3 tests/corpus/run.py fetch
python3 tests/corpus/run.py evaluate --reference --output tmp/corpus-evaluation
```

Use a new output directory for each run. `--ids` selects manifest IDs;
`--timeout` defaults to 60 seconds per stage. `--preview-pages` defaults to two;
text and page metadata cover all pages. With a custom Cargo target directory,
pass `--normalizer PATH/TO/release/examples/corpus-normalize`. `--bundle` selects
another runtime bundle. Omit `--reference` for conversion-only testing.

`fetch` never accepts changed bytes or updates pins. To add a case, select an
upstream path at a full commit, inspect its provenance, calculate its SHA-256 and
size, and add a distinct ID **including the format**. Do not replace a failing
fixture just to improve the success rate. Keep expected rejections separate from
documents that should render.

## What is measured

Each ordinary legacy input runs through three paths:

1. The actual packaged, sandboxed `davros-preview` executable.
2. LibreOffice rendering the original input directly.
3. The test-only `corpus-normalize` example calling the production sandbox and
   normalization code, followed by LibreOffice rendering the resulting OOXML.

This distinguishes losses introduced during legacy normalization from losses in
our PDF renderer. The example uses the root dependency/patch and is not a
separate converter project or runtime executable. Modern controls use the first
two paths. Encrypted files are tested only for clean rejection by Davros; a
timeout, crash, or output PDF does not count as successful rejection.

Reference processes use a fresh profile, highest macro-security setting, no
network, read-only system/input mounts, a private writable work directory, and
the bundle's Liberation font configuration. Bubblewrap must work; the runner
fails its preflight rather than falling back to an unrestricted reference tool.
Each stage has 4 GiB address-space and 256 MiB per-file limits. Timeout handling
kills the process group. Reference-tool failures are reported separately.

`results.json` records status, elapsed time, memory, binary/manifest/runner/font
hashes, tool versions, PDF page count and dimensions, and text metrics. Times are
single local runs with roughly 5 ms polling granularity, not robust benchmarks.
`peak_rss_mib` is `wait4`'s child high-water mark (including the fork/launcher
floor); namespace launchers may not propagate descendant memory. The separate
`sampled_peak_tree_rss_mib` samples aggregate live descendant RSS, can double-count
shared memory, and can miss brief peaks or reparented/namespace-isolated children.
Restricted `/proc` visibility can also undercount it. Treat reference-launcher
memory numbers as incomplete, not comparable to the direct Davros process.
Neither measure is a precise allocation total.

Text recall compares Unicode-normalized, case-folded **word multisets**, including
duplicate counts, to LibreOffice's extracted text. Precision also exposes extra
text. Reading order is deliberately ignored. A reference with no extracted words
has **no score**, not 100% recall. The score does not establish correct rendering,
image retention, table structure, or text order. CJK tokenization, line wrapping,
font substitution, field values, and PDF text extraction can affect it.

`report.html` links side-by-side PNGs of the first configured pages, along with
stage metrics and logs. Inspect those and the full PDFs before diagnosing a
layout issue. Spreadsheet page width/pagination intentionally differs from
LibreOffice; different page counts alone are not failure. LibreOffice is a
comparison renderer, not an authoritative Microsoft Office reference.

The corpus is opt-in and reports known defects without turning every fidelity
difference into a CI failure. `test.sh` runs the corpus runner's accounting tests
without downloading files or requiring LibreOffice. Promote specific defects to
asserted converter regressions as they are fixed.

## Fixed-defect regressions

After evaluating with `--reference`, assert the fixed DOC cases:

```sh
python3 tests/corpus/check_regressions.py tmp/corpus-evaluation
```

The six checks require `poi-word-PngPicture-doc`,
`poi-word-DiffFirstPageHeadFoot-doc`, `poi-word-footnote-doc`,
`poi-excel-DateFormats-xls`, and `poi-powerpoint-text-margins-ppt` in that run.
They verify original PNG bytes/proportions and ordinary paragraph styling, explicit page breaks and distinct
headers/footers, linked automatic notes, distinct date formats, and absence of
invented slide titles. Both normalized OOXML and rendered PDFs are checked where
applicable. They do not establish correct overall layout or image placement.
The first two checks fail against the original baseline; the four added checks
fail against the first DOC-fix evaluation.

`test.sh` also runs the complete Office Oxide unit suite, including synthetic
page-break round trips, image-scanner bounds/false-positive cases, and XLS
row/column dimensions. Those tests need no downloaded corpus or LibreOffice.

### First DOC fixes — 2026-10-13

The first follow-up run is available locally at
[`tmp/corpus-doc-fixes-full/report.html`](../../tmp/corpus-doc-fixes-full/report.html).
The original baseline remains unchanged.

| Case | Before | After |
| --- | --- | --- |
| POI `PngPicture.doc` | PNG absent from normalized OOXML/PDF | Original PNG bytes retained; visible in both PDFs |
| POI `DiffFirstPageHeadFoot.doc` | 1 page, 84.52% reference-word recall | 2 pages, distinct headers/footers, 100% recall |
| LibreOffice `tdf104239_numbering.doc` | Cover page collapsed into body; 2 pages | Separate cover page; 3 pages, matching reference count |

All 38 ordinary inputs still convert; all three encrypted inputs are cleanly
rejected. No crashes or timeouts occurred. The same original PPT fails in
LibreOffice; all 32 normalized legacy files render in LibreOffice. No fixture's
reference-word recall decreased. The numbering case gains an additional `37`
page-number token, slightly lowering multiset precision; its numbering/layout
remains imperfect. The restored PNG still uses fallback sizing and placement,
so image geometry is not fixed.

Validation: 1,228 Office Oxide unit tests, the standard sandbox/conversion suite,
five corpus-runner tests, and both fixed-defect corpus checks pass. Both new
corpus checks fail against the preserved baseline.

Still open: DOC note references/bodies and section geometry, original image
anchors/sizes, XLS charts and date formats, PPT shape/text placement and
headers/footers, and WMF rendering.

Evaluated runtime SHA-256: `41e8731b1c2d68ceef0c5807f3b613daa1eff392f2751045277ce526ebd2d5bb`.

### Second fidelity batch — 2026-10-13

The latest full report and supporting PDFs are in
[`tmp/corpus-fidelity-final/report.html`](../../tmp/corpus-fidelity-final/report.html).
The before/after comparisons below use the first DOC-fix run above.

| Case | Before | After |
| --- | --- | --- |
| POI `footnote.doc` | 16.67% reference-word recall; note bodies invisible | 100% recall/precision; automatic references and both bodies visible |
| POI `DateFormats.xls` | 72.73% recall; dates flattened to ISO strings | 100% recall/precision; numeric values and distinct date formats preserved |
| POI `SimpleChart.xls` | 29.13% recall | 47.24% recall from restored date formats; chart still missing |
| POI `PngPicture.doc` | Logo stretched into a 4:3 rectangle; prose promoted to a title | Natural 189:55 image proportions; ordinary paragraph styling |
| POI `text-margins.ppt` | Invented “Slide 1” title; 66.67% precision | No invented title; 100% precision and recall; positioning still wrong |

The new DOC path pairs automatic note references with their bodies via the
binary note tables, preserves reference positions through hidden/field text
and UTF-16 decoding, and uses positive note IDs distinct from reserved separator
IDs. Comments are written as comments rather than unreferenced endnotes.
Structured paragraphs retain explicit outline levels; the short/all-caps
heading guess is now limited to the fallback path without paragraph records.

All 38 ordinary inputs convert, all three encrypted inputs are cleanly rejected,
and there are no crashes/timeouts. The same original PPT fails in LibreOffice;
all 32 normalized legacy outputs render there. All 1,232 Office Oxide unit tests,
six corpus fidelity checks, and packaged-converter regression checks pass. The
standard sandbox suite also passed during this batch.

Removing fabricated slide titles lowers two token-recall scores: the
header/footer PPT goes from 50% to 35.71%, and the WMF crop PPT from 1.05% to 0%.
The old “Slide 1”/“Slide 2” strings happened to match reference words/numbers;
the decrease does not mean authored text was removed. The underlying missing
footer/page-number and WMF content remains unresolved. Blank graphics-only
slides remain genuine failures of fidelity even though conversion succeeds.

This is the stopping point for incremental fixes. The remaining major work is:

- **PPT layout and master inheritance:** retain shape coordinates, text margins,
  z-order, fills, and inherited audience content. The current text model lacks
  those coordinates; master/notes text also becomes an extra slide.
- **XLS charts:** parse the BIFF chart structure and its data/geometry; extracting
  labels alone cannot reconstruct a chart.
- **WMF:** the existing decoder covers a small placeable-polygon subset. The
  failing fixture uses non-placeable WMFs with text, fonts, polylines, and bitmap
  records, requiring substantially broader rendering support.

Still limited: custom note symbols and note-body formatting, DOC section/page
geometry, original image anchors/sizes, and JPEG/metafile natural sizing.
XLS dates using the 1904 epoch or unresolved regional built-in formats retain
the previous ISO-text fallback to avoid changing their dates or exposing raw
serials. Source chart, slide, and image placement is not recovered by these fixes.

Evaluated runtime SHA-256: `4f2e232c8e5fac151bf15cfcabe9f00d0421bd7110d2ba3141393a9a16438075`.


## ODF preview evaluation

The production converter supports ODT, ODS and ODP through the pinned, patched
`libreoffice-rs` backend. Office formats retain their existing converters.
Upstream revisions and checksums are in `sources.json`; the maintained patch is
`patches/libreoffice-rs-291b94a.patch`. See [PATCHES.md](../../PATCHES.md) for its
logical changes and limitations, and [SECURITY.md](../../SECURITY.md) for security
limits and validation.

`odf/` contains the maintained comparison runner, synthetic fixture generator,
pinned native corpus manifest, and compact report exporter. The native manifest
adds 18 LibreOffice QA documents and Akbar Ahmed’s MIT-licensed Writer template
(`Example file.odt`), pinned at `53a4119dfd2644fae4d4ec86bb6bfb1af4c5f520`.
Together with directly authored controls and LibreOffice exports of Office
fixtures, the evaluation covers 31 documents.
Downloaded inputs and generated reports remain ignored; upstream licenses are
retained under `licenses/` and included in report exports.

### Reproduce the evaluation

Use the reference-engine dependencies described above, then:

```sh
./build.sh
./test.sh
cargo build --release --locked --example corpus-normalize -j1
python3 tests/corpus/run.py fetch
python3 tests/corpus/run.py --manifest tests/corpus/odf/native-corpus.json fetch
python3 tests/corpus/odf/evaluate.py \
  --candidate output/native-preview/davros-preview --odf-only \
  --native-corpus tests/corpus/odf/native-corpus.json \
  --preview-pages 12 --output tmp/odf-evaluation
```

The evaluator automatically exports `tmp/odf-evaluation-share.tar.gz`. Copy that
single archive: it includes the report, inputs, PDFs, preview images and licenses,
without reference-engine profiles, caches, or working directories. To export an
existing result directory:

```sh
python3 tests/corpus/odf/share.py tmp/odf-evaluation tmp/odf-share
```

### Current coverage and limitations

All 30 cases converted with matching reference page counts and passing content
checks at the shapes/typography checkpoint. After security hardening, all 30
retained their previous candidate page counts and exact extracted text. The
security check was not a new pixel-difference evaluation.

Supported improvements include spreadsheet column widths, merges, formatting,
pagination, cached chart values, images, presentation fields, style inheritance,
bounded enhanced geometry, and selectable presentation text. See the patch
inventory for precise scope; these are previews, not complete Office-suite
renderers.

The eight-page shape control's mean foreground pixel mismatch improved from
59.77% to 38.78%; its first four pages improved from 56.43% to 14.26%. Pages 5–7
still expose unsupported 3D projection, lighting and advanced effects. Automatic
contrast colors, mixed text styles, highlighting, kerning, and arbitrary font
families remain incomplete. Dynamic date/time fixtures compare saved candidate
text against a refreshed reference time and remain visible in reports.

The local visual checkpoint is `tmp/odf-round29`; its compact export is
`tmp/odf-report-shapes-typography.tar.gz`. These are ignored local artifacts,
not files supplied by a checkout. Regenerate reports with the commands above.

### Writer template regression

`writer-template-example-odt` is a one-page Cassandra data-modeling example from
[libreoffice-writer-template](https://github.com/akbarahmed/libreoffice-writer-template).
It exercises decimal outline numbering, headings inside list wrappers, colored
callouts, a bordered multi-paragraph code block with explicit indentation, and
a centered table header with independently styled cell edges. Its upstream MIT
license is retained in `licenses/writer-template/LICENSE`; the manifest records
the pinned source path, size and SHA-256. No downloaded document is committed.

The updated renderer preserves all 202 reference tokens on one page, with no
off-page words. All 31 ODF cases convert and pass their semantic checks; the
previous 30 retain their page counts and token-recall scores. All 31 production
PDFs are byte-identical to the debug PDFs used in the full evaluation; the
packaged conversion tests and 99 ODF library tests also pass. Pixel equality is
not claimed: the template still differs in base-font appearance, footer color
and decoration, inline code borders, and some spacing. Its full comparison is
`tmp/odf-writer-template-share.tar.gz` (about 3 MiB), containing only report assets.

A focused before/after/reference comparison is available locally as
`tmp/writer-template-report.tar.gz` (about 472 KiB, 10 files), including the
source, its license, three PDFs, three page images and build/source provenance.

### Yocto kernel lab Unicode regression

Manual validation uses [Kernel-lab-2.6.odt](https://wiki.yoctoproject.org/wiki/images/b/bb/Kernel-lab-2.6.odt),
SHA-256 `ed840c2a06fba35c2cf98ba22b86701981cc20304ed9668f025e84df0e565922`.
The downloaded document remains local under ignored `files/yocto/`; it is not
part of the redistributable pinned corpus manifest. The packaged synthetic
Unicode test reproduces its U+2023 triangular-bullet failure without downloading
third-party material.

Liberation lacks U+2023. Bundling Noto Sans Regular fixes the fatal conversion
error while preserving the original selectable character. Build dependencies,
font copying, runtime licenses and release-package checks include the fallback.
The installed font adds 621,572 bytes (313,039 bytes with gzip -9); versions
provided by other distributions can differ. No converter binary changes are
needed for the font-only repair. All 31 existing ODF corpus cases retain exact
extracted text and page breaks with this fallback, and packaged conversion
regressions pass. The layout corrections below also change converter code.

The initial font-only fix produced 28 pages versus LibreOffice's 31, including
an extra first blank page. Follow-up layout fixes preserve heading page breaks,
cover-master selection, centered image geometry, fractional sizes, bullet-list
spacing/indentation, hanging paragraphs, footer logos/styles, and trailing code
padding. The updated preview has 31 pages, matching the reference, with the
cover on page one and introduction on page two, 99.95% reference-token recall,
and no off-page words. All 105 ODF library tests and packaged conversion tests
pass; the 31 production corpus PDFs match the evaluated debug PDFs byte for
byte. Font substitution and exact
wrapping still cause visual differences; page-count agreement is not a claim
of pixel equivalence.

Local inputs, PDFs and diagnostic outputs remain under `tmp/yocto/`. Copy only
`tmp/yocto-layout-report.tar.gz` for the before/after/reference comparison; it
contains the report and linked assets, without build caches or reference-engine
profiles. The broader ODF comparison is `tmp/odf-yocto-layout-share.tar.gz`.
