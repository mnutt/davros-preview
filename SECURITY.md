# Document conversion security

Review date: 2026-10-14. This is a source review and targeted regression testing,
not a claim that all parsers or deployment configurations are secure.

## Trust boundary and policy

Treat every uploaded document, embedded image/font, relationship, and generated
PDF as untrusted. The converter is a disposable subprocess. The launcher, input
snapshot, font bundle, and private job directory are trusted. Do not run it as
root or give it credentials. Conversion continues when optional kernel protections
are unavailable, and reports each missing protection on stderr. The preflight
JSON describes protections applied to its own process, not guarantees about a
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
- Check PDF bytes against 128 MiB before writing. Stage output privately and
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
   as registry crates. No complete advisory scan was performed in this review.
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
