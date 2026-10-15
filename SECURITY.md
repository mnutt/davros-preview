# Document conversion security

Latest review: 2026-10-15, using libreoffice-rs `327fa24`, docxide-pdf 0.17.1,
and Office Oxide 0.1.13 with the patches in sources.json. This is a source review
and targeted regression testing, not a proof that every document is safe.

The build was subsequently updated to libreoffice-rs `16532b3`. The additions
include presentation preset geometry, hatch mapping, SmartArt fallback, and text
layout work. The active-content regressions were rerun for this pin; the broad
source review below records the earlier `327fa24` snapshot.

## Parser execution review: 2026-10-15

The working deployment assumption is **no Landlock inside Sandstorm**. The
principal question was whether document content can intentionally invoke a shell,
interpreter, native executable, external resource loader, or executable PDF action.
No such server-side code-execution route was found in the reviewed conversion
paths. This does not establish the absence of memory-safety vulnerabilities in
all dependencies, nor does it make a compromised worker harmless inside a grain.

### Findings requiring attention

1. **Confirmed denial of service: deeply nested DOCX run wrappers abort the worker.**
   `docxide-pdf/src/docx/runs.rs:619` recursively descends `smartTag`, `customXml`,
   `ins`, `sdt`, `fldSimple`, and alternate-content wrappers without an explicit
   depth budget. A synthetic 1,486-byte DOCX with 10,000 nested `w:smartTag`
   elements passed archive validation and aborted with SIGABRT / stack overflow
   in about 0.01 seconds. This is a worker crash, not demonstrated memory corruption
   or code execution. Worker-crash availability impact is low priority for this
   Sandstorm deployment; it is not treated as a release blocker. `panic = "abort"`
   and the parent subprocess boundary prevent treating it as a recoverable parse
   error inside that worker. Fix in docxide-pdf:
   bound structural depth before recursive consumers, or use bounded iterative
   traversal; review the other recursive XML consumers too. Reproduce with
   `python3 tests/probe-docx-depth.py` (intentionally fails on the current binary).

2. **Output hardening: arbitrary URI schemes survive as PDF links.**
   A DOCX hyperlink with `javascript:alert(1)` and an ODT `text:a` with the same
   target both produce URI annotations containing that URL. Relevant sites are
   `docxide-pdf/src/pdf/assembly.rs:157` and
   `lo_core/src/pdf_canvas.rs:358,668`. PDF string escaping was present; no PDF
   syntax-injection path or automatic `/JavaScript`, `/Launch`, or `/OpenAction`
   was demonstrated. This is not server-side execution and is not a demonstrated
   PDF.js exploit: current PDF.js allows only HTTP, HTTPS, FTP, mailto, and tel
   URLs and binds links only from validated URLs
   ([URL validation](https://github.com/mozilla/pdf.js/blob/master/src/shared/util.js#L411-L455),
   [annotation binding](https://github.com/mozilla/pdf.js/blob/master/src/display/annotation_layer.js#L898-L958)).
   The inspected Davros component uses browser-native `<object>/<embed>` rather
   than bundling PDF.js; other viewers were not tested. Optionally restrict output
   schemes in both PDF writers, preserving internal destinations. That would make
   the output policy independent of viewer choice.

3. **Maintenance exposure: unmaintained font parser handles untrusted DOCX fonts.**
   An OSV query of all 168 locked package/version entries returned only
   [RUSTSEC-2026-0192](https://rustsec.org/advisories/RUSTSEC-2026-0192.html), an
   informational unmaintained notice for `ttf-parser` 0.25.1, not a known code
   execution vulnerability. DOCX embedded fonts reach `ttf_parser::Face::parse`
   in `docxide-pdf/src/fonts/embed.rs`, as well as subsetting and some outline
   processing. Plan a maintained replacement upstream. This was a name/version
   database check, not cargo-audit or a complete audit of custom fork changes,
   vendored C, glibc, the kernel, or the browser.

### Execution and external-resource paths reviewed

- `src/main.rs` dispatches directly to Rust libraries; it does not launch the
  LibreOffice application, Microsoft Office, a shell, or an external converter.
  Macro-enabled content is not made safe merely by its filename; the reviewed
  paths have no VBA, XLM, Basic, JavaScript, Python, or plugin execution engine.
- Office Oxide records macro presence as metadata and recognizes OLE objects;
  legacy conversion serializes a new OOXML document. DOCX object handling uses
  preview images. None of these paths activates OLE/ActiveX or executes an
  embedded program. The `.spawn` in Office Oxide is a Rust worker thread.
- XLSX preview uses saved cell values, including blank results for uncached
  formulas. Its conditional-formatting evaluator uses cached scalars. The Calc
  formula evaluator that exists elsewhere is a fixed arithmetic/string-function
  dispatcher with no process/network functions; unknown functions return errors.
  DOCX DDE/INCLUDETEXT-style fields do not dispatch to system commands.
- Package relationships resolve to in-memory ZIP entries, not extracted host
  paths. DOCX image targets are passed to `zip.by_name`; XLSX/PPTX external
  relationships are skipped. No archive extraction or document-controlled
  filesystem write path was found in the production import path.
- Presentation SVG uses resvg with string and data image resolvers disabled;
  scripts are not evaluated. External XML entities did not access the canary.
  Font discovery is restricted to the configured trusted bundle. These findings
  do not depend on Landlock denying a request after the fact.
- A source scan of the target dependency graph found no process/network sinks in
  the reviewed library paths. `memmap2` exposes executable-map APIs, but the font
  discovery call uses a read-only mapping. No runtime call to the executable-map
  APIs or a dynamic-library loader was found. Procedural macros/build scripts are
  build-time code and are a separate supply-chain trust boundary.
- Unsafe Rust and native code still exist in dependencies, including codecs and
  compression (zstd includes C); “Rust implementation” is not a proof of memory
  safety. DOCX font-subsetting failure may embed the original font, and JPEG data
  may be copied into the PDF, so the viewer still processes untrusted media.

### Tests and limits of the evidence

`python3 tests/test-active-content.py --trace` passed 19 inputs, including the
nine-format controls and synthetic DDE/include fields, external relationships,
spreadsheet formulas, ODF script content, SVG script/external images, and XML
external entities. The trace mode injects ENOSYS into the Landlock ABI query and
suppresses PR_SET_DUMPABLE solely to keep syscall arguments observable. It
verifies degraded hardening is reported, then checks for no extra exec calls,
no non-thread process creation, no socket/network calls, and no canary-path
access. It also checks that canary text did not appear in output. Normal mode
runs in `test.sh`; syscall tracing is opt-in and requires strace/ptrace access.
The opaque VBA/OLE parts are inert markers, not a valid malicious macro corpus.
The PDF token checks cover these fixtures, not a general PDF sanitizer.

The existing archive-size/output-publication protections remain useful. Resource
exhaustion is not comprehensively closed: DOCX recursion is a confirmed example;
aggregate sheet/page/image work is not fully budgeted, and the WebP decoder does
not use the explicit preview limits applied to PNG/GIF/BMP. No new exploit was
confirmed for those latter cases. The sibling Davros launcher still has the
previously documented whole-job termination and output-descriptor validation
issues, relevant after a worker compromise, not evidence of an initial parser
exploit. Its 128 MiB output cap is also lower than this converter's 256 MiB cap.

For completeness, a separate harmless diagnostic using the actual sandbox setup
confirmed that Landlock ABI 9 did not prevent anonymous executable mappings or
execution of an in-memory ELF that only exits with status 42. This is a sandbox
limitation, not a document exploit; it is not the focus of the Sandstorm review.
No memory-corruption exploit, sanitizer/fuzzer campaign, or live-grain attack
was performed. Production conversion behavior was not changed by this review.

## Prior containment review: 2026-10-14

The following records the earlier containment review and its remaining priorities.

## Trust boundary and policy

Treat every uploaded document, embedded image/font, relationship, and generated
PDF as untrusted. The converter is a disposable subprocess. The launcher, input
snapshot, font bundle, and private job directory are trusted. Do not run it as
root or give it credentials. Conversion continues when optional kernel protections
are unavailable. Stderr summarizes active Landlock filesystem isolation or its
failure reason and warns about unexpected hardening failures. Expected absence
of newer ABI capabilities is recorded in the preflight JSON. That JSON describes
protections applied to its own process, not guarantees about a
future process or the entire host.

Landlock supplements the enclosing sandbox. When filesystem isolation is absent,
a compromised converter can access anything its Unix identity and outer sandbox
allow, including other files in the same Davros grain. A second process with the
same identity is not a filesystem security boundary. Even active Landlock does
not deny all metadata operations or every kind of networking. Standard I/O also
remains open intentionally. See the [kernel's Landlock documentation](https://www.kernel.org/doc/html/latest/userspace-api/landlock.html)
for ABI negotiation and limitations.

## Protections and findings addressed here

- Detect actual successful application of each kernel protection, not just its
  advertised ABI. Fault-injection tests cover unavailable/disabled/denied syscalls,
  failures after ABI discovery, independently denied network/scoping layers,
  tighter inherited limits, and descriptor fallback failures.
- Bound inputs and actual ZIP decompression before document parsing. Legacy
  normalization uses explicit binary readers and validates generated OOXML.
- Check PDF bytes against 256 MiB before writing (current converter limit). Stage output privately and
  publish without overwriting existing files, symlinks, or hardlinks. This is
  application behavior, not a containment measure against arbitrary code execution.
- Share ODF XML subtrees instead of cloning them recursively in two tree views.
  Bound depth and structural expansion before construction. Resolve presentation
  fields once per shared subtree. Reject excessive populated ODS cells before
  repeated-row expansion.
- Keep bundled font discovery, SVG rasterization limits, and external SVG resource
  restrictions from the existing fidelity patches. Embedded fonts and other image
  formats remain parser attack surfaces.

## Launcher review and next priorities

The sibling Davros checkout's `server/document-preview.js` already copies from an
opened input descriptor, creates private job directories, passes an explicit
small environment, ignores stdin, serializes renders, bounds the pending job
count and diagnostic tail, imposes a 60-second deadline, validates output magic
and size, and cleans up scratch. That checkout was inspected, not modified here.
Its current API accepts only DOCX/XLSX/PPTX; integration of the additional formats
must preserve those checks.

1. **Enforce a job boundary outside the parser.** Kill the whole job, including
   descendants, on cancellation or timeout. The current launcher kills only the
   immediate child. A process group helps with ordinary descendants, but a
   compromised process can escape it; cgroups or a supervisor-owned sandbox are
   stronger where available. Bound memory, tasks and temporary disk externally;
   resource limits inside the converter are optional and an output limit does
   not bound total scratch usage. Feature-detect these mechanisms inside Sandstorm.
   For strong isolation without Landlock, investigate a supervisor-mediated
   worker with only the input, fonts and scratch exposed. Do not assume an
   unprivileged grain can create namespaces or configure cgroups.
2. **Make degradation visible operationally.** Run preflight inside the actual
   grain at integration/deployment time; retain successful-conversion security
   warnings in server diagnostics. Currently Davros collects stderr but discards
   it on success. Bound/rate-limit repeated messages and avoid logging document
   contents. Treat a killed probe as a failed check, not as an empty report.
3. **Contain expanded work, not just compressed bytes.** Add aggregate budgets
   for cells across sheets, paragraphs/runs, pages, images' decoded pixels, font
   tables and formula/layout work. ODS cell strings can themselves be large;
   their count cap is not a memory guarantee. Legacy intermediate OOXML is
   currently size-checked after serialization; without RLIMIT_FSIZE it can consume
   scratch before rejection. PDF bytes are also built in memory before the size
   check. Add limits at these allocation/write sites, preserving explicit errors.
4. **Treat worker output as attacker-controlled.** In Davros, open output with
   no-follow semantics, verify the opened descriptor is a regular bounded file,
   and publish from that same object. Its current stat/open/chmod path sequence
   assumes the worker left a regular file. Our no-clobber writer protects normal
   conversion, but cannot constrain a compromised worker. Audit cache pruning
   and publication under the same assumption, especially surviving descendants.
5. **Exercise adversarial input continuously.** Fuzz ZIP/CFB, XML, ODF shapes,
   embedded image/font ingestion and full conversions under time/memory limits.
   Seed with the public corpus and the regression bombs; keep minimized failures.
   Include malformed local/central ZIP disagreements, duplicate/path-normalized
   names, unusual encodings, external references, truncated binary records,
   huge dimensions and repeated structures. Multiple ZIP/parser implementations
   mean a preflight pass is not proof of equivalent downstream interpretation.
6. **Track dependency and viewer vulnerabilities.** Run a RustSec-aware dependency
   check in CI and schedule updates, reviewing vendored path dependencies as well
   as registry crates. The earlier review did not include an advisory scan; see the 2026-10-15
   dependency check above.
   Keep PDF.js/browser rendering patched; test annotation URLs and generated PDF
   actions. The HTTP path already sets PDF content type, nosniff and restrictive
   CSP, but those headers alone do not establish viewer isolation. Review the
   actual iframe/worker origin and link handling separately.

Avoid broad syscall filtering added without a representative compatibility test:
font/image libraries, thread startup and allocators may need unexpected calls.
A small, tested additional syscall policy could deny unnecessary process creation
and networking even on kernels without Landlock, but must itself be detected and
reported. Upstream Sandstorm's legacy policy explicitly blocks installing seccomp
filters as well as nested namespaces, so neither is a generally usable in-grain
fallback; see its [supervisor policy](https://github.com/sandstorm-io/sandstorm/blob/master/src/sandstorm/supervisor.c++). A policy returning errno can degrade gracefully; an outer policy using
SIGSYS/KILL cannot be recovered from by ordinary syscall error handling.

## Validation limits

The local host supports Landlock ABI 9. Tests simulate errno failures with seccomp;
they do not prove behavior on every old kernel, architecture, or Sandstorm build.
There is no live-grain test in this repository. FD cleanup without close_range
and /proc is bounded and explicitly reported as unverified. Tests for application
limits are necessary even when the kernel sandbox succeeds.

Local validation completed: 88 ODF unit tests, the output-publication regression,
packaged conversions for all nine formats, nested-XML and repeated-cell rejection,
and sandbox fault injection including a production conversion with Landlock
blocked. All 30 inputs from `tmp/odf-round29` retained their candidate page counts
and exact extracted text. This was a content/pagination regression check, not a
new pixel-difference evaluation. The two generated presentation controls previously
recorded around 1,806/1,810 MiB peak RSS now measured 15.87/16.51 MiB with `wait4`,
consistent with removing recursive subtree duplication. Preparation tests and the
five corpus-runner tests also passed.
