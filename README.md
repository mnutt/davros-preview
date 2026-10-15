# davros-preview

A sandboxed document-to-PDF converter used by Davros. The Rust build,
upstream patches, fonts, and converter regression tests live here; Davros owns
HTTP requests, permissions, job scheduling, cancellation, caching, and the UI.

The `davros-preview` executable supports these formats:

| Input | Converter |
| --- | --- |
| DOC, DOCX | Office Oxide 0.1.13 (DOC → DOCX), docxide-pdf 0.17.1 |
| XLS, XLSX, PPT, PPTX | Office Oxide 0.1.13 (XLS → XLSX, PPT → PPTX), Davros libreoffice-rs fork |
| ODT, ODS, ODP | Davros libreoffice-rs fork, revision `16532b3` |

XLS/XLSX and PPT/PPTX render through
[mnutt/libreoffice-rs, davros-fixes](https://github.com/mnutt/libreoffice-rs/tree/davros-fixes),
pinned to revision `16532b3f0ded4b2e05296d114e2eacd91827ed23` for reproducible builds.
Office Oxide normalizes legacy DOC/XLS/PPT to DOCX/XLSX/PPTX first; DOC/DOCX
continues to use docxide-pdf. The former `DAVROS_PREVIEW_XLSX_RENDERER` switch
is no longer used.

PDF text remains selectable. Microsoft spreadsheet pages widen to fit all columns at their
natural size, while still paginating vertically. ODS uses source page geometry and
paginates horizontally and vertically. Liberation Sans, Serif,
and Mono (regular, bold, italic, bold italic), plus Noto Sans Regular for
additional Unicode coverage, are bundled. These fonts do not cover every script.
OpenDocument characters missing from all bundled fonts render as outlined boxes,
with their original Unicode retained for copying and searching; conversion emits
a warning and continues. Font substitution can change wrapping and pagination.

## Build and test

Use Linux amd64, Rust 1.98.0 (pinned in `rust-toolchain.toml`), Python 3.12+,
`patch`, a C/C++ toolchain, and Liberation/Noto Sans fonts. Poppler is needed for tests.
On Debian 13:

```sh
sudo apt-get install build-essential python3 patch fonts-liberation fonts-noto-core poppler-utils
./build.sh
./test.sh
./package.sh
```

The default is one Cargo job to accommodate small build VMs. Set
`CARGO_BUILD_JOBS` and `CARGO_TARGET_DIR` to override. `prepare.py` validates
source archive checksums before extracting and applying any declared patches; the
libreoffice-rs fork is a Cargo Git dependency pinned to a commit, without a local
patch or a copy in `vendor/`. Cargo uses
the checked-in lockfile. Dependencies are downloaded on the first build.

[PATCHES.md](PATCHES.md) describes each logical dependency change, its regression
coverage and limitations, and how to reassess it when upgrading upstream crates.

`output/native-preview/` contains the runtime bundle. `dist/` contains
`davros-preview-v0.3.4-linux-amd64.tar.gz` and its `.sha256` file. The archive
contains a single `native-preview/` directory, matching Davros's existing output
layout. Build dependencies and test executables are not included.

Release builds optimize for size (`opt-level = "z"`, full LTO, one codegen unit,
stripped symbols, and abort-on-panic). Measured locally on Linux amd64 with Rust
1.98.0 and the pinned fork on 2026-10-15:

| Artifact | Size |
| --- | ---: |
| Executable | 8,398,472 bytes (8.01 MiB) |
| Runtime bundle, including fonts and licenses | 13.19 MiB unpacked |
| Runtime `.tar.gz` | 6.03 MiB |

The previously built executable with office2pdf was 39.26 MiB. After removing
it, the previous `opt-level = "s"` / thin-LTO settings produced 10.15 MiB;
`"z"` / full LTO reduced that to 7.90 MiB at revision `327fa24`. The table above
reflects the current pin, including its additional presentation support. These
are local measurements, not cross-platform guarantees or a renderer throughput
benchmark. The executable
still needs the bundled fonts and host system libraries.

Release CI runs on Ubuntu 22.04, using glibc 2.35 as its compatibility baseline
for Davros's Debian 13 package. Locally built binaries inherit the build host's
libc requirements; use CI release artifacts for distribution.

## Run the converter

The caller supplies a separate input file and an existing, private output
scratch directory. Paths below should be absolute:

```sh
mkdir -p /tmp/preview-job
DAVROS_PREVIEW_FONTS="$PWD/output/native-preview/fonts" \
FONTCONFIG_FILE="$PWD/output/native-preview/fonts.conf" \
RAYON_NUM_THREADS=2 \
output/native-preview/davros-preview /path/to/input.xlsx /tmp/preview-job/preview.pdf
```

Use the same command for DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, and ODP inputs.
Input extensions are case-insensitive. Conversion finishes before the
PDF is available. The caller should enforce its own deadline and terminate the
subprocess on cancellation (Davros uses 60 seconds).

Before parsing, the executable attempts each available protection independently:
Linux Landlock, inherited-descriptor cleanup, disabled process dumping,
no-new-privileges, and resource limits. Stderr reports the enforced Landlock ABI
(e.g. `Using Landlock ABI 6 for preview`), or explains why Landlock filesystem
isolation is unavailable. Missing capabilities requiring newer ABIs are expected
and appear in `--check-sandbox` JSON rather than individual warnings. Unexpected
hardening failures still produce named warnings; conversion continues with the
remaining protections.
Landlock ABI 1 provides basic filesystem restrictions; later ABIs add truncation,
device ioctl, TCP, Unix socket, signal, and UDP restrictions. A successful ABI
query alone is not treated as successful enforcement.

When filesystem isolation is active, reads are limited to input, bundled
fonts/configuration and scratch, writes to scratch, and program execution is
denied. Landlock does not restrict every operation (including some metadata
operations). Without it, the converter retains the launcher's filesystem access.
Sandstorm protects other grains, but does not by itself isolate this subprocess
from files within its own grain. Availability depends on the actual kernel and
outer sandbox policy; do not infer it from a kernel version or a host-side test.

With the same environment and valid paths, inspect actual available protections:

```sh
output/native-preview/davros-preview --check-sandbox /path/to/input.xlsx /tmp/preview-job/preview.pdf
```

This applies protections in the checking process, emits JSON with per-feature
`enabled`/`detail` fields and `degraded`, and exits without parsing or producing a
PDF. Missing protections return success under the best-effort policy; invalid
configuration fails. Run it inside the actual grain. Each conversion repeats the
checks. A seccomp policy that kills rather than returns an error for a syscall can
terminate the probe; the launcher must handle abnormal exits as well as JSON.
Descriptor cleanup uses `close_range`, then `/proc/self/fd`, then bounded
individual closes; the last fallback reports completeness as unverified.

See [SECURITY.md](SECURITY.md) for the threat model, review findings and remaining
hardening priorities.

Legacy conversion runs in the same sandbox as PDF rendering. Intermediate OOXML
files live in the private scratch directory and are deleted on normal completion
or error; the caller must remove scratch after cancellation or process failure.
Generated OOXML passes the same size and decompression checks as direct input.
No external office suite is required at runtime.

Limits: 32 MiB input (including intermediate OOXML), 10,000 ZIP entries, 32 MiB
per decompressed entry, 128 MiB total decompression, 256 MiB PDF output, and
4 GiB address space when the kernel permits the resource limit. Input and ZIP
limits are enforced by the application. PDF size is checked before publication
even without resource limits; existing outputs (including links) are never
overwritten. Rendering can allocate memory before its output-size check. ODF
also bounds recursive XML expansion and populated ODS cells (100,000 per sheet).

## Releases

Push this project to its GitHub repository, then push a version tag matching
`Cargo.toml`, for example `v0.3.4`. The workflow builds and tests before publishing
the archive and SHA-256 file. Branches and pull requests also build/test and
upload workflow artifacts, without publishing a release.

When adopting a release, Davros should pin both its exact URL/version and SHA-256
and extract the verified archive under `output/`. Publishing here does not
automatically update the version pinned by Davros.

## Tests and legacy conversion

`test.sh` runs the Office Oxide and ODF renderer unit suites (including our conversion regressions) and
exercises the packaged executable, selectable text, spreadsheet
number formatting, prefixed SpreadsheetML, wide-sheet pagination, malformed
input, legacy conversion, temporary-file cleanup, and sandbox enforcement. The
small synthetic Office fixtures came from Davros's regression generator, preserved as `tests/fixture-source.cjs` (requires
Node and `archiver` only if regenerating fixtures). No private user documents are
committed here.

The checked-in legacy fixtures are synthetic conversions of `basic.docx`,
`basic.xlsx`, and `basic.pptx` using LibreOffice; see `tests/legacy-fixtures.txt`
for regeneration commands. LibreOffice is only needed to regenerate fixtures.

Legacy previews preserve readable, selectable content but have incomplete layout
fidelity, particularly slide positioning, images, charts, and styles. The XLS
patch preserves explicit column widths and row heights, including blank rows;
it does not fix default dimensions, visibility, or chart/image anchors. DOC normalization now preserves explicit page breaks,
automatic footnote/endnote references, and PNG content/proportions. Structured
DOC prose no longer gets promoted to invented headings. XLS conversion
keeps numeric values and supported number/date formats, and untitled PPT slides
stay untitled. Custom note marks, 1904/regional date-format fidelity, and original
image placement still need work.

The optional public corpus evaluation covers 41 pinned fixtures from
[Apache POI](https://github.com/apache/poi/tree/trunk/test-data) and LibreOffice's
[Writer](https://github.com/LibreOffice/core/tree/master/sw/qa/extras),
[Calc](https://github.com/LibreOffice/core/tree/master/sc/qa/unit/data), and
[Impress](https://github.com/LibreOffice/core/tree/master/sd/qa/unit/data) tests.
It focuses on legacy DOC/XLS/PPT, with six modern controls and three encrypted
inputs expected to be rejected. Downloads are checksum-verified and kept out of
the runtime bundle and Git. See [tests/corpus/README.md](tests/corpus/README.md)
for reproduction commands and [the baseline evaluation](tests/corpus/BASELINE.md)
for findings. A successful conversion is not a fidelity pass.

## OpenDocument previews

ODT, ODS and ODP run directly in the same sandboxed binary, with no LibreOffice
installation or intermediate Office conversion. The renderer uses the commit-pinned
libreoffice-rs fork, which also renders XLSX and PPTX. DOCX uses docxide-pdf,
and Office Oxide normalizes legacy DOC/XLS/PPT before rendering. Fonts are
separate in the runtime bundle.

The ODF regression corpus includes 30 documents: 18 native LibreOffice QA files,
three directly authored controls, and nine exported Office controls. The standard
test command generates the three controls locally and checks the packaged binary,
including uppercase extensions, text retention, page fields, cached cell formats,
hidden sheets and invalid inputs. The larger fidelity comparison is optional;
see [the corpus guide](tests/corpus/README.md).

ODF previews remain approximate. Enhanced 2D paths and equation-driven shapes are
rendered, but extruded 3D shapes, gradients, mixed text styles,
font substitution, some table layouts and advanced chart features are incomplete.
Spreadsheet formulas use saved results. Presentation footer declarations and slide
numbers are resolved per slide when enabled; date/time fields retain saved text
rather than using the server clock. SVG artwork is rasterized with bounded size;
external image references and SVG text are disabled. Do not treat a successful
conversion as a guarantee of visual fidelity.

## Licensing

Project code is Apache-2.0, extracted from Davros. See `THIRD_PARTY_NOTICES` for
converter modifications. Runtime archives contain collected dependency notices
and the Liberation and Noto Sans font licenses. Office Oxide is MIT/Apache-2.0.
