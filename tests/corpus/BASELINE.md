# Initial public-corpus evaluation — 2026-10-13

The converter is robust on this small selection, but successful legacy
conversion frequently produces a materially incomplete preview. Office Oxide
normalization is responsible for several confirmed losses; the PPTX renderer
also drops retained WMF images. **38 successful conversions is not 38 fidelity
passes.** No renderer or normalization fixes were made during this evaluation.

The full measurements are in [baseline.json](baseline.json). Inputs and source
revisions are recorded in [manifest.json](manifest.json). The local PDFs, logs,
normalized OOXML, and side-by-side previews are in
[`tmp/corpus-baseline-v2/report.html`](../../tmp/corpus-baseline-v2/report.html).
That generated directory is ignored; reproduce it using the [runner](README.md).

## Coverage and outcome

| Format | Ordinary files converted | Encrypted files cleanly rejected | Text comparisons available | Full reference-word retention |
| --- | ---: | ---: | ---: | ---: |
| DOC | 11/11 | 1/1 | 10 | 6 |
| XLS | 11/11 | 1/1 | 9 | 5 |
| PPT | 10/10 | 1/1 | 7 | 5 |
| DOCX | 2/2 | — | 2 | 2 |
| XLSX | 2/2 | — | 2 | 2 |
| PPTX | 2/2 | — | 1 | 0 |

There were no Davros crashes or timeouts. LibreOffice rendered 37 of the 38
ordinary original files and all 32 normalized legacy outputs. It rejected
POI's `slideshow/pictures.ppt` with “source file could not be loaded”; that case
has no original-reference fidelity score. Cases without extracted reference
words, such as image-only documents, also have no text score.

These are 41 feature-selected documents totaling about 1.44 MiB, not a random
sample, large-document stress test, or Microsoft Office reference suite. The
reference version was LibreOffice 26.2.5.2, using the same bundled Liberation
font configuration. Only the first two pages were rasterized for the report;
text and page metadata cover the complete PDFs. The visual findings below are
targeted inspections, not a visual audit of every page.

## Confirmed normalization defects

| Fixture | Observation | Evidence locating the loss |
| --- | --- | --- |
| POI `document/footnote.doc` | Footnote and endnote text disappear; only “Test text” remains. Word recall is 16.7%. | Both Davros and LibreOffice rendering the normalized DOCX lose `TestFootnote` and `TestEndnote`. |
| POI `document/PngPicture.doc` | The PNG logo disappears, despite 100% text retention. | The normalized DOCX has no media entries; both normalized renderings omit the logo. |
| POI `document/DiffFirstPageHeadFoot.doc` | Two pages collapse to one; second-page headers and footers disappear. Recall is 84.5%. | LibreOffice reproduces the loss from normalized DOCX. The separate modern DOCX control retains both pages and all reference words. |
| POI `spreadsheet/SimpleChart.xls` | The embedded chart disappears; date presentation also changes. Recall is 29.1%, affected by both chart text and date formatting. | The chart is absent in both normalized renderings. |
| LibreOffice `sc/qa/unit/data/xls/embedded-chart.xls` | Charts disappear while worksheet data remains. Recall is 52.8%. | The normalized XLSX has the same loss when rendered by LibreOffice. |
| POI `spreadsheet/DateFormats.xls` | Distinct US/UK date formats become the same ISO-style text. Recall is 72.7%. | Identical changed date strings occur in both normalized renderings; this is formatting loss, not missing rows. |
| POI `slideshow/text-margins.ppt` | Four horizontally positioned text boxes become a vertical list, with an added “Slide 1” heading. Text recall remains 100%. | LibreOffice renders the same changed arrangement from normalized PPTX. |
| POI `slideshow/headers_footers.ppt` | Two original slides become three, including a “Slide Master”/notes-text slide. The per-slide footer is lost. Recall is 50%, also influenced by date fields. | The normalized PPTX reproduces the extra slide and footer differences. |
| LibreOffice `sd/qa/unit/data/ppt/FillPatterns.ppt` | The visible pattern-filled shapes disappear; only an added “Slide 1” label remains. | LibreOffice also fails to reproduce the shapes from normalized PPTX. The reference is graphics-only, so text recall cannot detect this failure. |
| LibreOffice `sc/qa/unit/data/xls/file-with-png-image.xls` | The PNG survives but its aspect/placement changes. | Both normalized renderings show the changed image geometry. |

## Defects spanning normalization and PDF rendering

LibreOffice's `sd/qa/unit/data/ppt/crop.ppt` is the clearest example:

- The original-reference PDF has positioned graphs and a logo.
- The normalized PPTX retains two WMF media files. LibreOffice can render their
  content, with 100% reference-word retention, but placement/cropping is badly
  changed and objects overlap near the upper-left corner.
- Davros renders only “Slide 1”, giving 1.05% word recall. The current
  `office2pdf` image-dispatch code supports EMF conversion but has no WMF path;
  retained WMF assets are classified as unsupported.

Preserving legacy placement alone will not fix that document. The PDF stage
also needs a strategy for retained WMF content, or an explicit unsupported-content
diagnostic rather than silent omission.

## Metric limitations observed in this run

- LibreOffice's `cell-multi-line.xls` scores 75% word recall because one reference
  line extracts as `Line1Line2Line3` while Davros extracts separate words. All
  three line labels remain. Do not file this as a confirmed missing-text defect.
- Modern `bar-chart.pptx` scores 78.3% because the renderers choose different
  axis tick labels/ranges. This is not evidence that source body text was lost.
- Date fields, date formatting, pagination, and duplicated chart labels affect
  multiset recall. Consult full extracted text and the images before triage.
- 100% recall says nothing about missing images or displaced text. The PNG and
  text-margin fixtures above demonstrate this directly.

## Suggested order of follow-up work

1. Preserve legacy DOC images, footnotes/endnotes, and section/page structure.
   These are confirmed missing-content cases with small reproductions.
2. Preserve PPT slide/master distinctions and object geometry; surface dropped
   WMF content. Near-empty “successful” PDFs are especially misleading.
3. Preserve XLS charts and date formatting, then image anchors/aspect ratios.
4. Promote each repaired case to an asserted regression using source-content or
   geometry checks. Keep broad reference-image comparisons diagnostic until
   tolerances and reference behavior are established.

Run a larger and more diverse selection after addressing these cases. This
first batch establishes actionable failures, not a production fidelity rating.
