# Local dependency patches

This is the semantic inventory of our vendored changes: what each change does,
why we carry it, and what to check when upgrading. The files in `patches/` are
aggregate diffs per crate, not one patch per logical fix. They are tied to the
versions below; successful application to another version would not establish
that the changes are still correct or needed.

Exact upstream archive versions and SHA-256 checksums live in
[sources.json](sources.json). [prepare.py](prepare.py) verifies the archive,
normalizes Rust sources and `Cargo.toml` to LF, and applies each diff with
`patch -p1 --batch`. A source-and-patch hash stamp controls reuse of the extracted tree.
Changing a patch causes that crate's `vendor/` directory to be replaced, so save
any vendor edits in the patch before preparing again. The stamp is not a check
of the current vendor file contents.

Source paths below are relative to the named upstream crate. Validation names
refer to tests we currently have; where coverage is only a smoke test or manual
inspection, that is stated explicitly. No upstream acceptance status is implied.

## docxide-pdf 0.17.1

Patch: [docxide-pdf-0.17.1.patch](patches/docxide-pdf-0.17.1.patch).

### D1. Restrict font discovery to the configured bundle

In `src/fonts/discovery.rs`, `font_directories()` treats
`DAVROS_PREVIEW_FONTS` as an exclusive, platform-separated list of directories.
When unset, upstream discovery remains available. This lets Davros render with
its packaged fonts inside the filesystem sandbox instead of searching host font
directories. This is a Davros integration requirement, not a document fix.

Validation: packaged DOC/DOCX conversions in `tests/test-conversion.py`, together
with the sandbox checks in `test.sh`. These are integration checks, not exhaustive
tests of environment-variable parsing or directory precedence.

### D2. Map common font families to Liberation

The same file maps Arial, Helvetica, Calibri, Aptos and `sans-serif` to Liberation
Sans; Times New Roman, Times, Cambria and `serif` to Liberation Serif; Courier
New, Courier, Consolas and `monospace` to Liberation Mono. Lookup still uses the
requested bold/italic face. This substitution is intentional Davros policy and
can change line wrapping and pagination; it is not exact font reproduction.

Validation: packaged conversion smoke tests and visual inspection of corpus
PDFs. There is no dedicated assertion for every alias.

### D3. Return rendered PDF bytes to the caller

`src/lib.rs` adds `render_docx_to_pdf`, using the existing parser and renderer.
The CLI can now enforce its output limit and publish through the same exclusive
staging-file path as other formats. Existing upstream file-writing APIs remain
available. Validate packaged DOC/DOCX output and unavailable-Landlock symlink
refusal (`test-sandbox.py`).

## office_oxide 0.1.13

Patch: [office_oxide-0.1.13.patch](patches/office_oxide-0.1.13.patch).
This patch spans parsers, the intermediate representation (IR), conversion, and
OOXML writers. Constructor updates, exhaustive enum matches and adjusted upstream
tests belong to the corresponding change below, not independent features.

### O1. Preserve XLS row heights and column widths

`src/xls/workbook.rs` reads BIFF `COLINFO` widths (1/256 character units) and
`ROW` heights (twips), bounds-checks them, and resets dimensions between sheets.
`src/convert_xls.rs` carries those dimensions through the IR and retains blank
rows with explicit heights, including trailing rows and rows outside the cell
grid. `src/ir.rs` adds `Table.column_widths_chars`; the constructor adjustment in
`src/convert_docx.rs` supplies an empty default for non-spreadsheet tables.

`src/create.rs` transfers dimensions to the XLSX writer. `src/xlsx/write.rs`
adds row-height setters, emits `ht`/`customHeight` even for blank rows, and writes
column widths without rounding them to two decimal places. Heights must be finite
and within 0–409.6 points at the writer boundary; BIFF parsing accepts 2–8192
twips. These are one end-to-end change: a reader-only fix would still lose sizing.

Validation: `dimensions_survive_biff_to_xlsx` checks widths, heights, blank rows
and isolation between sheets. Packaged XLS tests check retained row content.
Hidden rows/columns, default dimensions and original drawing anchors are not
implemented by this change.

### O2. Find DOC pictures stored in WordDocument

`src/doc/document.rs` keeps `WordDocument` as the image-stream fallback when
opening `Data` fails. Some producers store their image records there and omit
`Data`. Image extraction remains lazy; the implementation does not scan both
streams and duplicate normal pictures.

Validation: corpus `poi-word-PngPicture-doc` checks the exact original PNG hash
in normalized DOCX and image presence in both rendered PDFs. This recovers image
bytes, not their original position or author-specified size.

### O3. Make the DOC image scan tolerate false headers and reject truncation

`src/doc/images.rs` requires the expected record version, a complete in-bounds
record, and a valid decoded image signature before skipping to the record end.
Invalid candidates advance one byte so a false header cannot hide a later image.
Truncated lengths are no longer clamped into apparently valid pictures. This is
especially relevant to O2's scan through a mixed-content WordDocument stream.

Validation: `invalid_candidate_does_not_hide_later_picture` and
`truncated_picture_is_not_accepted`, plus O2's corpus case.

### O4. Preserve explicit DOC page breaks through DOCX generation

`src/doc/piece_table.rs` retains formfeed (`0x0C`) in structured text while the
plain-text API still produces newlines. `src/ir.rs` introduces
`InlineContent::PageBreak`. `src/convert_doc.rs` distinguishes page and soft line
breaks and retains leading, trailing and break-only content.

`src/create.rs` and `src/docx/write.rs` carry page breaks through both DOCX run
conversion paths, prevent coalescing across them, and emit `<w:br w:type="page"/>`.
Text/HTML/Markdown rendering in `src/ir_render.rs` and other format paths degrade
them to ordinary line breaks. Port these enum consumers with the parser change.

Validation: `explicit_page_breaks_survive_sanitizing_and_docx_writing`,
`structured_text_keeps_page_breaks_distinct_from_soft_breaks`, and corpus
`poi-word-DiffFirstPageHeadFoot-doc` (two pages with distinct first/later headers
and footers). This does not recover all section geometry or section-break modes.

### O5. Pair automatic DOC footnote/endnote references with their bodies

New `src/doc/notes.rs`, registered by `src/doc/mod.rs`, reads paired reference
and body PLC tables for footnotes/endnotes. It validates lengths, counts and
character bounds, ignores the undefined final reference CP, and recognizes
automatic marks at source character `0x02`. Positive, separately numbered IDs
avoid reserved separator IDs. `src/doc/document.rs` stores the parsed notes.

`src/doc/piece_table.rs` exposes sanitized-text offset mapping;
`src/doc/papx.rs` maps original UTF-16 character positions into visible text,
including supplementary Unicode and filtered field instructions/hidden text.
`src/convert_doc.rs` places references among formatted runs, links and breaks,
including table/list/heading paths, and emits the paired bodies without also
dumping the same note substory as duplicate content.

Validation: `pairs_note_bodies_and_ignores_undefined_final_cps`,
`note_anchors_follow_utf16_cps_and_skip_field_instructions`, and corpus
`poi-word-footnote-doc`. Custom-symbol marks, rich note-body formatting and all
original numbering settings are not covered. The structured reference path does
not add equivalent support to Word 6 or the no-PAPX fallback.

### O6. Write automatic note-body marks in DOCX

`src/docx/write.rs` adds a run-level note-body reference and emits styled
`<w:footnoteRef/>` or `<w:endnoteRef/>`. It prepends the mark to the first paragraph,
or creates a leading paragraph if necessary, without dropping the stored body.
The paragraph clone support belongs to this change. Existing custom-marker
behavior remains available.

This supplies the body-side mark corresponding to the main-text reference from
O5. Validation: the footnote corpus regression requires matching positive IDs,
automatic body marks, and visible footnote/endnote text in both rendered PDFs;
the full upstream unit suite also exercises note writing.

### O7. Classify DOC comments as comments

`src/convert_doc.rs::subdocument_label` returns `Comment` with the capitalization
expected by the existing comment-author dispatch in `src/create.rs`. Previously
comment content could become an unreferenced endnote, including a collision with
reserved note ID zero. This does not implement missing main-text comment anchors.

Validation: the footnote corpus case contains a comment; `TestComment` must not
appear as PDF body text while the real notes remain visible.

### O8. Do not infer headings for structured DOC paragraphs

`src/convert_doc.rs` uses parsed outline levels for structured paragraphs instead
of promoting short first lines or all-caps prose to headings when no explicit
heading was found. The text-only fallback retains its heuristic. Removing the
whole-document `has_structured_headings` flag and related arguments is part of
this change.

Validation: `structured_prose_is_not_promoted_to_a_heading` checks ordinary prose
and explicit headings. The PNG corpus case checks absence of invented Heading
styles; visual inspection confirms its ordinary sentence is no longer a large
title. This can also change inferred document/section titles.

### O9. Preserve XLS cell types and number formats

`src/xls/workbook.rs::NumberFormats::semantics` exposes the source cell type,
raw numeric value and declared/built-in number format.
`src/convert_xls.rs` populates existing typed IR fields so the XLSX writer does
not have to reinterpret display strings. Dates retain their distinct formats;
text such as `007` remains text. Custom format overrides, including ID zero, are
retained.

The writer uses the 1900 date epoch. Until the IR carries workbook epoch, 1904
dates fall back to existing ISO display text; unresolved regional date formats
also use text rather than exposing a serial or shifting the date.

Validation: `typed_dates_and_text_survive_xls_to_xlsx` covers raw date values,
formats, leading-zero text and the two fallbacks. Corpus
`poi-excel-DateFormats-xls` checks distinct visible date strings. This is not
formula evaluation or full Excel number-format compatibility.

### O10. Preserve natural PNG proportions for fallback legacy images

`src/convert_xls.rs::append_legacy_images`, shared by legacy DOC/XLS/PPT fallback
image conversion, reads PNG dimensions from a validated signature and IHDR and
sets IR pixel width/height. Writers can then use the natural proportions instead
of a generic 4:3 rectangle. Despite its source filename, this is not XLS-only.

Validation: `poi-word-PngPicture-doc` requires a DOCX extent ratio of 189:55,
alongside original image bytes and PDF image presence. This does not recover
original anchors/scaling, handle dimensions for every image format, or change
the separately resolved PPT image path.

### O11. Do not invent titles for untitled PPT slides

`src/convert_ppt.rs` leaves `Section.title` absent when the source has no title,
instead of inserting `Slide N`. `src/ppt/document.rs` updates the matching test
expectation. Generated titles were becoming visible content absent from the
source.

Validation: the upstream PPT test and corpus `poi-powerpoint-text-margins-ppt`
check retained source text without `Slide 1`. Removing fabricated words can lower
word-recall scores that accidentally counted them as matches. This does not fix
shape coordinates, stacking order, master inheritance or extra master-text slides.

### O12. Keep editable package ZIP timestamps deterministic

`src/core/editable.rs` sets every saved ZIP entry's timestamp to the ZIP epoch
(1980-01-01). The ZIP writer's default can use the current time when its `time`
feature is enabled, making unchanged saves differ even with sorted entries.

Validation: `test_saving_the_same_package_twice_produces_the_same_bytes` now waits
across ZIP's two-second timestamp resolution before comparing repeated saves.

## Upgrading and validating

1. Compare the new upstream implementation against each numbered change above.
   Distinguish Davros policy from bug fixes. Drop an item only when its required
   behavior is supplied upstream or we deliberately change that requirement.
2. Port remaining changes and their regression tests to a pristine new crate.
   Keep parser/IR/writer changes together. Regenerate the per-crate diff against
   the pristine, LF-normalized source; avoid whole-tree formatting churn. Do not
   rely on fuzzy patch application as evidence of a correct port.
3. Update `sources.json`, affected patch filenames, dependency paths in
   `Cargo.toml`, `Cargo.lock`, and this inventory. Review other version-specific
   references. Save vendor edits first, then verify preparation from a clean
   extracted tree, rather than relying on a matching stamp.
4. Build the runtime and run the standard checks:

   ```sh
   ./build.sh
   ./test.sh
   ```

   `test.sh` runs the Office Oxide library tests, sandbox checks, packaged
   conversion regressions and corpus-runner accounting tests. It does not run
   the downloaded reference corpus or exhaustively test every policy item above.
5. For fidelity changes, evaluate a fresh corpus output directory and assert the
   fixed defects:

   ```sh
   cargo build --release --locked --example corpus-normalize -j 1
   python3 tests/corpus/run.py fetch
   python3 tests/corpus/run.py evaluate --reference --output tmp/corpus-upgrade
   python3 tests/corpus/check_regressions.py tmp/corpus-upgrade
   ```

   See [the corpus guide](tests/corpus/README.md) for LibreOffice/Bubblewrap
   prerequisites and focused runs. Inspect normalized OOXML, rendered PDFs and
   report images as well as text scores: successful conversion and matching text
   do not establish correct layout. Compare against a retained pre-upgrade run.

The CLI dispatch, sandbox/resource limits, intermediate-file cleanup and corpus
harness are repository code, not additional dependency patches. See
[src/main.rs](src/main.rs), [src/legacy.rs](src/legacy.rs),
[src/lib.rs](src/lib.rs) and [tests/corpus/README.md](tests/corpus/README.md).


## libreoffice-rs renderer

The ODT/ODS/ODP, XLS/XLSX and PPT/PPTX renderers use the checksum-pinned
Davros fork at `16532b3f0ded4b2e05296d114e2eacd91827ed23`. Its `davros-fixes`
branch contains the imported fixes as logical commits plus the XLSX and PPTX
corpus work. No local patch is applied. The prefixed-XLSX regression fixtures
verify the fork's foreign-namespace sheet fix.

The inventory below describes changes maintained in the fork. Reproduction
steps, validation and limitations are in the
[ODF evaluation notes](tests/corpus/README.md#odf-preview-evaluation). Rerun the
native ODF and original control corpus when updating the pinned revision.

Production integration adds bundled Unicode font discovery through
`DAVROS_PREVIEW_FONTS` (`lo_core/src/unicode_font.rs`). It takes precedence over
upstream font overrides and avoids system-font discovery inside the sandbox.
Presentation master fields (`lo_impress/src/import.rs`) resolve enabled footer,
header, slide-number, slide-count and slide-name fields per slide, retaining saved
date/time values. The importer regression covers visible and hidden master fields
across multiple slides. Complex enhanced geometry and mixed-run typography remain
open fidelity work.

`sources.json` pins the source archive checksum; `prepare.py` stages extraction
before replacing the vendor tree. `test.sh` runs the ODF library
tests and generated ODF controls through the packaged binary, alongside all
existing Office and sandbox checks. Runtime dependency notices include inherited
workspace metadata and the upstream MIT license.

### Enhanced geometry and presentation typography

- `lo_impress/src/odf_shapes.rs` interprets ODF enhanced paths instead of replacing
  custom shapes with rectangles. It handles move/line/cubic/quadratic segments,
  close/end/fill/stroke controls, elliptical quadrants and arcs; evaluates bounded
  modifier/equation references and arithmetic/trigonometric expressions; and
  preserves mirrors and compound holes. Ordinary paths, polygons and polylines
  use the same SVG route. Generated artwork passes through the existing bounded,
  self-contained SVG rasterizer; shape text stays selectable. Geometry tests cover
  equations, cycles, malformed/excessive input, real triangle/ellipse paths, a
  transparent ring hole and visible hairlines. Extrusion and unsupported transforms
  retain the previous fallback. Gradients, 3D lighting and per-face shading are
  not implemented; subpixel strokes have a minimum preview width of 0.5 pt.
- `lo_core/src/style.rs` adds explicit named-style inheritance so a nested span's
  default family style cannot reset an inherited frame/paragraph property.
  `lo_impress/src/import.rs` uses it for text color, family, size, bold/italic and
  alignment, and imports source padding and vertical text alignment. The
  regression combines a white parent style, a black family default, a styled
  child span, a serif family and centered vertical alignment.
- `lo_impress/src/pdf.rs` uses the selected base font's widths for wrapping and
  horizontal alignment and places text blocks according to vertical alignment.
  `lo_core/src/font_metrics.rs` reuses upstream Writer's Times metrics alongside
  Helvetica and fixed-width Courier metrics. `lo_core/src/pdf_canvas.rs` adds
  Helvetica-BoldOblique, with its PDF resource and Unicode style flags;
  `lo_writer/src/font_metrics.rs` handles this additional font variant. Existing
  Writer font selection is unchanged. Mixed styling within a text box, automatic
  contrast colors, kerning and arbitrary font families remain incomplete.

The packaged regression generates an ODP with enhanced ring geometry and bold
italic text, checks that artwork is emitted, and verifies selectable text uses
its actual bold-italic PDF font resource. The downloaded eight-page shape corpus
and presentation controls provide the visual comparison; successful path parsing
alone is not a visual correctness test.

### ODF security: XML cloning and repeated spreadsheet cells

`crates/lo_core/src/xml_parser.rs` shares subtrees with `Arc` between `children`
and ordered `items`. Upstream cloned both recursively, making allocation grow
exponentially with nesting. Both views retain the same node identity; accessors
still return `&XmlNode`. A depth limit of 64 and a conservative 128 MiB structural
budget bound recursive traversal and construction, including CDATA and implicitly
closed input. This budget is not an exact allocator/RSS measurement.

`crates/lo_impress/src/import.rs` resolves presentation fields once per subtree
using copy-on-write, then reconnects the ordered view to the updated children;
traversing both views recursively would reintroduce exponential work.
`crates/lo_math/src/import.rs` adapts its fallback node to shared ownership.
When upgrading, preserve sharing, bounded construction and tests for node
identity, excessive nesting, and presentation field resolution.

`crates/lo_calc/src/import.rs` rejects more than 100,000 expanded populated cells
per sheet before materializing repeated rows. Per-axis bounds alone allow their
product to exhaust memory. Errors propagate through `from_ods_bytes`; the limit
can reject unusually large legitimate sheets. Regression tests cover a tiny
package describing a million rows with 16,384 populated columns.

Validation: `cargo test -p lo_core -p lo_calc --lib`, packaged ODF conversions,
and the existing ODF corpus. These limits do not cover every decoder, layout
algorithm, or the total cell count across multiple sheets.


### Writer technical-document templates

`lo_writer/src/import.rs` now reads decimal ODF outline rules, including start
values, displayed ancestor levels and label prefixes/suffixes. Heading-only list
wrappers are flattened so their outline labels do not acquire extra bullets.
Counters reset below each new ancestor. Alphabetic/Roman outline formats and
per-heading restart overrides remain unsupported.

The importer preserves `text:s` spaces as nonbreaking spaces through wrapping,
with a 10,000-space cap per element. It imports inherited paragraph backgrounds,
solid borders, padding and point-precision margins instead of rounding all
margins to whole millimeters. `lo_core/src/style.rs` stores these ODF-specific
properties without changing non-ODF defaults. `lo_core/src/writer.rs` also retains
each table cell edge independently; explicit `none` overrides the shorthand.

`lo_writer/src/layout.rs` respects source heading sizes and spacing, uses the
bundled Liberation families’ natural line-box metrics for ODF percentage line
spacing, and accounts for padding in layout. It paints paragraph backgrounds and
solid borders per page fragment. Adjacent identically styled bordered, shaded
paragraphs with joining enabled share a box; their paragraph spacing contributes
to line spacing. This is approximate for wrapped or mixed-size joined paragraphs.
Table cells honor their paragraph alignment and individual edge borders.
Non-solid border styles, inline text borders, rich footer styling, arbitrary
font metrics and exact outline tab positioning remain incomplete.

Regression coverage includes nested heading wrappers and counter resets,
inherited boxes and precise margins, bounded explicit spaces, individual table
edges, indentation after wrapping, source heading styles, and a packaged-binary
synthetic template. The pinned public Writer example and the full ODF corpus
provide visual and selectable-text comparisons. Keep these logical changes when
updating the fork; do not replace them with fixture-specific strings.

### Writer cover pages, lists, and code-listing pagination

The Yocto kernel-lab document exposed independent layout errors after the missing
U+2023 glyph was resolved by packaging Noto Sans Regular:

- `lo_writer/src/import.rs` honors inherited `break-before="page"` on headings
  as well as paragraphs, and ignores a break before the first flow block. A
  first-page master with a following body master and shared geometry supplies
  distinct first-page headers/footers. Empty first-page headers no longer reserve
  a fictitious header band. Different page geometries and arbitrary mid-document
  master switches remain outside this change.
- `lo_core/src/style.rs` retains fractional font sizes in thousandths of a point
  alongside the existing integer field, plus signed ODF first-line indentation.
  Writer uses the precise size for runs and line boxes; other importers retain
  their existing defaults. This preserves the source's 10.5 pt body text.
- `lo_core/src/writer.rs` and the Writer importer preserve ODF list indentation
  and bullet characters by level. Writer removes its additional generic list
  gaps when source spacing is present, and applies absolute source indentation
  to nested lists. Numbering continuation and all numbering formats are not
  implemented by this bullet-list change.
- `lo_writer/src/layout.rs` discards end-of-paragraph space padding before
  wrapping while retaining explicit leading/interior spaces. Long trailing
  `text:s` runs in code listings had created empty lines and an extra page.
  Hanging first lines receive their own available width; ODF tabs advance toward
  half-inch stops, approximated with the selected font's space width. Arbitrary
  tab-stop definitions, decimal tabs and leader characters remain incomplete.
- ODF image groups retain graphic alignment and, for non-wrapping paragraph
  anchors, vertical offsets and the anchor paragraph's line space. Footer raster
  images are registered once and painted at their source offsets on normal pages;
  first/left-page overrides suppress the normal artwork. Image placement inside
  complex nested frames, transformed groups and independently styled repeated
  instances remains approximate.
- Page fields retain styled spans, fractional sizes, tabs, explicit line breaks,
  and dynamic page numbers/counts. Their measured height reserves footer space.
  `lo_calc/src/pdf.rs` handles the new shared styled-field variant recursively;
  Calc's own field import and formatting are otherwise unchanged.

`lo_writer/src/lib.rs` only initializes the new optional list metadata for
Markdown lists. Unit tests cover first-master selection and heading breaks,
fractional sizes, bullet levels, image alignment/offsets, trailing code padding,
hanging first lines, and styled multi-line page fields. The packaged test builds
a two-page synthetic cover document, checks page-specific footers and selectable
text, and verifies the PDF retains a 10.5 pt font size. No public input is needed
for these tests.

The Yocto comparison now has 31 pages, matching LibreOffice, with the title on
page one and introduction on page two. The full existing 31-case ODF corpus
retains its page counts and passes content checks. This is not pixel equivalence:
font substitution, exact wrapping/line breaking, and more complex ODF layouts
remain approximate. See the corpus guide and local comparison report for the
measured result and remaining differences.

### Missing OpenDocument glyphs render as tofu

`lo_core/src/unicode_font.rs` keeps normal font fallback for supported characters.
When coverage is exhausted, it subsets a bundled TrueType font's U+25A1 outlined
square and assigns a distinct CID to each unsupported character. The shared PDF
writer in `lo_core/src/pdf_canvas.rs` emits an explicit CID-to-glyph map: all
these CIDs draw the square, while ToUnicode retains each original codepoint,
including supplementary-plane characters. This avoids both a document-wide
conversion failure and loss of text identity when multiple characters share the
same visual placeholder. CIDs are split across fonts if necessary to stay within
the 16-bit PDF encoding limit. One bounded diagnostic reports the missing count
and up to eight codepoints. A missing usable fallback font still returns an error;
the production Liberation/Noto bundle provides the square.

Packaged regressions cover ODT, ODS and ODP with repeated and distinct unsupported
BMP/supplementary private-use characters mixed with supported text. They check
successful conversion, warning output, exact text extraction, explicit glyph
mapping, and successful Poppler rasterization. Microsoft Office renderers are
unchanged.
