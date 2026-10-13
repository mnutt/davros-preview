# davros-preview

A small, sandboxed Office-to-PDF converter used by Davros. The Rust build,
upstream patches, fonts, and converter regression tests live here; Davros owns
HTTP requests, permissions, job scheduling, cancellation, caching, and the UI.

The `davros-preview` executable supports these formats:

| Input | Converter |
| --- | --- |
| DOC, DOCX | Office Oxide 0.1.13 (DOC → DOCX), docxide-pdf 0.17.1 |
| XLS, XLSX, PPT, PPTX | Office Oxide 0.1.13 (XLS → XLSX, PPT → PPTX), office2pdf 0.8.1 |

PDF text remains selectable. Spreadsheet pages widen to fit all columns at their
natural size, while still paginating vertically. Only Liberation Sans, Serif,
and Mono (regular, bold, italic, bold italic) are bundled. Font substitution can
change wrapping and pagination; scripts outside this font set are not supported.

## Build and test

Use Linux amd64, Rust 1.98.0 (pinned in `rust-toolchain.toml`), Python 3.12+,
`patch`, a C/C++ toolchain, and Liberation fonts. Poppler is needed for tests.
On Debian 13:

```sh
sudo apt-get install build-essential python3 patch fonts-liberation poppler-utils
./build.sh
./test.sh
./package.sh
```

The default is one Cargo job to accommodate small build VMs. Set
`CARGO_BUILD_JOBS` and `CARGO_TARGET_DIR` to override. `prepare.py` validates
upstream crate checksums before extracting and applying `patches/`; Cargo uses
the checked-in lockfile. Dependencies are downloaded on the first build.

`output/native-preview/` contains the runtime bundle. `dist/` contains
`davros-preview-v0.1.0-linux-amd64.tar.gz` and its `.sha256` file. The archive
contains a single `native-preview/` directory, matching Davros's existing output
layout. Build dependencies and test executables are not included.

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

Use the same command for DOC, DOCX, XLS, XLSX, PPT, and PPTX inputs.
Input extensions are case-insensitive. Conversion finishes before the
PDF is available. The caller should enforce its own deadline and terminate the
subprocess on cancellation (Davros uses 60 seconds).

The executable enables Linux Landlock before parsing Office content, closes
inherited descriptors other than standard I/O, and disables process dumping.
It can read only the copied input, bundled fonts/configuration, and scratch;
only scratch is writable. Execution of other programs is denied. Linux Landlock
ABI 3 or newer is required; unavailable sandboxing fails closed. Newer ABIs add
TCP, Unix socket, signal, and UDP restrictions. Metadata operations such as stat
and chmod are not fully restricted. This supplements Sandstorm's grain sandbox.
Sandstorm's experimental seccomp policy currently blocks these Landlock calls.

Legacy conversion runs in the same sandbox as PDF rendering. Intermediate OOXML
files live in the private scratch directory and are deleted on normal completion
or error; the caller must remove scratch after cancellation or process failure.
Generated OOXML passes the same size and decompression checks as direct input.
No external office suite is required at runtime.

Limits: 32 MiB input (including intermediate OOXML), 10,000 ZIP entries, 32 MiB
per decompressed entry, 128 MiB total decompression, 128 MiB PDF output, and
4 GiB address space.

## Releases

Push this project to its GitHub repository, then push a version tag matching
`Cargo.toml`, for example `v0.1.0`. The workflow builds and tests before publishing
the archive and SHA-256 file. Branches and pull requests also build/test and
upload workflow artifacts, without publishing a release. No release has been
published by this extraction.

When adopting a release, Davros should pin both its exact URL/version and SHA-256
and extract the verified archive under `output/`. Davros's existing source/build
integration is deliberately unchanged until that first release is published.

## Tests and legacy conversion

`test.sh` runs the Office Oxide XLS dimensions patch regression and
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
it does not fix default dimensions, visibility, or chart/image anchors.

For broader testing, useful upstream corpora include
[Apache POI test-data](https://github.com/apache/poi/tree/trunk/test-data),
[LibreOffice Writer](https://github.com/LibreOffice/core/tree/master/sw/qa/extras),
[Calc](https://github.com/LibreOffice/core/tree/master/sc/qa/unit/data), and
[Impress](https://github.com/LibreOffice/core/tree/master/sd/qa/unit/data).
A future corpus runner should pin source revisions and file hashes, record
conversion failures/time/memory, check content and geometry, and compare rendered
pages against references. A successful parse is not a fidelity pass. These
corpora have not yet been imported or run by this project.

## Licensing

Project code is Apache-2.0, extracted from Davros. See `THIRD-PARTY-NOTICES` for
converter modifications. Runtime archives contain collected dependency notices
and the Liberation font license. Office Oxide is MIT/Apache-2.0.
