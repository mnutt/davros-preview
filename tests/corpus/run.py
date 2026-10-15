#!/usr/bin/env python3
"""Fetch pinned public fixtures and evaluate conversion separately from fidelity."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LEGACY = {'.doc': '.docx', '.xls': '.xlsx', '.ppt': '.pptx'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified(path, record):
    if not path.is_file() or digest(path) != record['sha256']:
        raise ValueError(f'Missing or changed corpus file: {path}; run fetch')
    if 'size' in record and path.stat().st_size != record['size']:
        raise ValueError(f'Wrong size: {path}')


def validate_manifest(manifest):
    for field in ['id', 'file']:
        values = [f[field] for f in manifest['fixtures']]
        if len(values) != len(set(values)):
            raise ValueError(f'Duplicate fixture {field}')
    for fixture in manifest['fixtures']:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', fixture['id']):
            raise ValueError('Unsafe fixture ID')
        for key in ['path', 'file']:
            path = Path(fixture[key])
            if path.is_absolute() or '..' in path.parts:
                raise ValueError(f'Unsafe fixture {key}')
        if not re.fullmatch(r'[0-9a-f]{64}', fixture['sha256'] or ''):
            raise ValueError('Every fixture must have a SHA-256 pin')


def fetch(manifest):
    for fixture in manifest['fixtures']:
        target = HERE / 'files' / fixture['file']
        if target.exists():
            verified(target, fixture)
            continue
        source = manifest['sources'][fixture['source']]
        repo = source['repository'].removeprefix('https://github.com/')
        url = f"https://raw.githubusercontent.com/{repo}/{source['revision']}/{urllib.parse.quote(fixture['path'])}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(fixture['size'] + 1)
        if len(data) != fixture['size'] or hashlib.sha256(data).hexdigest() != fixture['sha256']:
            raise ValueError(f'Checksum/size mismatch: {url}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print('Fetched', fixture['file'], flush=True)
    for key, source in manifest['sources'].items():
        for notice in source['license_files']:
            verified(HERE / 'licenses' / key / notice['path'], notice)
    print(f"Verified {len(manifest['fixtures'])} fixtures and upstream notices")


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def tree_rss_kib(pid):
    """Sample live descendants too: namespace launchers may not propagate wait4 RSS."""
    total = 0
    pending = [pid]
    while pending:
        current = pending.pop()
        try:
            status = Path(f'/proc/{current}/status').read_text()
            rss = re.search(r'^VmRSS:\s+(\d+)', status, re.M)
            total += int(rss[1]) if rss else 0
            children = Path(f'/proc/{current}/task/{current}/children').read_text()
            pending.extend(int(child) for child in children.split())
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return total


def run(command, directory, timeout, env=None):
    """wait4 gives per-process peak RSS, including children, rather than a cumulative maximum."""
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    reaped = False
    peak_tree_rss = 0
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        proc = subprocess.Popen([str(x) for x in command], stdout=stdout, stderr=stderr,
                                env=env, start_new_session=True, preexec_fn=limits)
        try:
            while True:
                peak_tree_rss = max(peak_tree_rss, tree_rss_kib(proc.pid))
                pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    reaped = True
                    break
                if time.monotonic() - started > timeout:
                    timed_out = True
                    os.killpg(proc.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(proc.pid, 0)
                    reaped = True
                    break
                time.sleep(0.005)
        finally:
            # Also reap helper processes on interruption or abnormal tool exit.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not reaped:
                _, status, usage = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
    return {'exit_code': proc.returncode, 'timeout': timed_out,
            'seconds': round(time.monotonic() - started, 3),
            'peak_rss_mib': round(usage.ru_maxrss / 1024, 2),
            'sampled_peak_tree_rss_mib': round(peak_tree_rss / 1024, 2),
            'stderr_tail': (directory / 'stderr.log').read_text(errors='replace')[-3000:]}


def pdf_metrics(path):
    if not path.is_file() or not path.read_bytes()[:5] == b'%PDF-':
        return None
    try:
        info = subprocess.check_output(['pdfinfo', str(path)], text=True, timeout=20)
        pages = int(re.search(r'^Pages:\s+(\d+)', info, re.M)[1])
        geometry = subprocess.check_output(['pdfinfo', '-f', '1', '-l', str(pages), str(path)],
                                           text=True, timeout=20)
        sizes = re.findall(r'^Page\s+\d+ size:\s+([\d.]+) x ([\d.]+)', geometry, re.M)
        text = subprocess.check_output(['pdftotext', '-raw', str(path), '-'],
                                       text=True, timeout=20)
        path.with_suffix('.txt').write_text(text)
        return {'pages': pages, 'page_sizes_pt': [[float(w), float(h)] for w, h in sizes],
                'text_characters': len(text.strip()), 'bytes': path.stat().st_size}
    except (subprocess.SubprocessError, ValueError, TypeError) as error:
        return {'inspection_error': str(error)}


def tokens(text):
    return Counter(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def compare(actual, reference):
    """Multiset recall detects missing/repeated text without assuming reading order."""
    a = tokens(actual.with_suffix('.txt').read_text())
    r = tokens(reference.with_suffix('.txt').read_text())
    matched = sum((a & r).values())
    return {'reference_tokens': sum(r.values()), 'actual_tokens': sum(a.values()),
            'token_recall': round(matched / sum(r.values()), 4) if r else None,
            'token_precision': round(matched / sum(a.values()), 4) if a else None,
            'missing_tokens_sample': (r - a).most_common(20)}


def libreoffice(source, work, bundle):
    """Fresh profile, no network, read-only input/runtime, private writable scratch."""
    profile = work / 'profile' / 'user'
    profile.mkdir(parents=True, exist_ok=True)
    (profile / 'registrymodifications.xcu').write_text('''<?xml version="1.0"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
</oor:items>''')
    command = ['bwrap', '--die-with-parent', '--unshare-net', '--unshare-pid',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/etc', '/etc']
    for path in ['/bin', '/sbin', '/lib', '/lib64']:
        if Path(path).exists():
            command += ['--ro-bind', path, path]
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--ro-bind', str(source), '/input' + source.suffix,
                '--ro-bind', str(bundle), '/bundle', '--bind', str(work), '/work',
                '--chdir', '/work', '--clearenv', '--setenv', 'PATH', '/usr/bin',
                '--setenv', 'HOME', '/work', '--setenv', 'LANG', 'C.UTF-8',
                '--setenv', 'FONTCONFIG_FILE', '/bundle/fonts.conf',
                '--setenv', 'XDG_CACHE_HOME', '/work/cache',
                '--setenv', 'SAL_USE_VCLPLUGIN', 'svp',
                '/usr/bin/libreoffice', '-env:UserInstallation=file:///work/profile',
                '--headless', '--nologo', '--nodefault', '--norestore',
                '--convert-to', 'pdf', '--outdir', '/work', '/input' + source.suffix]
    return command


def preview(pdf, metrics, count):
    if not metrics or 'pages' not in metrics:
        return []
    images = []
    for page in range(1, min(metrics['pages'], count) + 1):
        prefix = pdf.parent / f'page-{page}'
        subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                        '-scale-to', '800', '-png', str(pdf), str(prefix)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        images.append(prefix.with_suffix('.png'))
    return images


def write_report(results, output):
    rows = []
    for item in results['fixtures']:
        metric = item.get('comparison', {})
        recall = metric.get('token_recall')
        pages = item['davros'].get('pdf', {}).get('pages', '—')
        reference = item.get('reference', {}).get('pdf', {}).get('pages', '—')
        rows.append(f"<tr><td><a href='#{html.escape(item['id'])}'>{html.escape(item['file'])}</a></td>"
                    f"<td>{item['status']}</td><td>{pages}/{reference}</td>"
                    f"<td>{f'{recall:.1%}' if recall is not None else '—'}</td>"
                    f"<td>{item['davros']['seconds']}</td><td>{item['davros']['peak_rss_mib']}</td></tr>")
    details = []
    for item in results['fixtures']:
        panels = []
        for label, key in [('Davros', 'davros'), ('LibreOffice original', 'reference'),
                           ('LibreOffice normalized OOXML', 'normalized_reference')]:
            stage = item.get(key)
            if not stage:
                continue
            images = ''.join(f"<a href='{html.escape(p)}'><img loading='lazy' src='{html.escape(p)}'></a>"
                             for p in stage.get('previews', []))
            panels.append(f'<div><h3>{label}</h3>{images}<pre>{html.escape(json.dumps(stage, indent=2))}</pre></div>')
        details.append(f"<section id='{html.escape(item['id'])}'><h2>{html.escape(item['file'])}</h2>"
                       f"<p>{html.escape(item['purpose'])}</p><div class='panels'>{''.join(panels)}</div>"
                       f"<pre>{html.escape(json.dumps({k: v for k, v in item.items() if 'comparison' in k}, indent=2))}</pre></section>")
    (output / 'report.html').write_text('''<!doctype html><meta charset="utf-8"><title>Davros corpus evaluation</title>
<style>body{font:15px system-ui;margin:24px;background:#eee;color:#222}table{border-collapse:collapse}td,th{padding:6px 12px;border:1px solid #bbb;text-align:left}section{margin-top:40px}.panels{display:flex;gap:16px}.panels>div{flex:1;min-width:0}img{width:100%;background:white}pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1751a8}</style>
<h1>Davros corpus evaluation</h1><p>Conversion success is not a fidelity pass. Token recall is an order-independent text diagnostic; it does not measure images, layout, correctness, or all writing systems. Page sizes/pagination intentionally differ for spreadsheets. Previews show only the first configured pages.</p>
''' + '<pre>' + html.escape(json.dumps(results['summary'], indent=2)) + '</pre>'
        + '<table><tr><th>Fixture</th><th>Status</th><th>Pages Davros/LO</th><th>Text recall</th><th>Seconds</th><th>Peak RSS MiB</th></tr>'
        + ''.join(rows) + '</table>' + ''.join(details))
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


def evaluate(args, manifest):
    if args.timeout <= 0 or args.preview_pages < 0:
        raise ValueError('Timeout must be positive; preview page count must be nonnegative')
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new/empty output directory to avoid stale results')
    for tool in ['pdfinfo', 'pdftotext', 'pdftoppm'] + (['bwrap', 'libreoffice'] if args.reference else []):
        if not shutil.which(tool):
            raise ValueError(f'Missing tool: {tool}')
    binary = bundle / 'davros-preview'
    if not binary.is_file() or not args.normalizer.is_file():
        raise ValueError('Build the runtime bundle and corpus-normalize example first')
    selected = [f for f in manifest['fixtures'] if not args.ids or f['id'] in args.ids]
    if args.ids and set(args.ids) != {f['id'] for f in selected}:
        raise ValueError('Unknown fixture ID')
    for fixture in selected:
        verified(HERE / 'files' / fixture['file'], fixture)
    output.mkdir(parents=True, exist_ok=True)
    if args.reference:
        probe = output / 'reference-preflight'
        command = libreoffice((HERE / 'files' / selected[0]['file']).resolve(), probe, bundle)
        command = command[:command.index('/usr/bin/libreoffice') + 1] + ['--version']
        checked = run(command, probe, args.timeout)
        if checked['exit_code'] != 0:
            raise RuntimeError(f"Reference sandbox unavailable: {checked['stderr_tail']}")
    env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
               FONTCONFIG_FILE=str(bundle / 'fonts.conf'), RAYON_NUM_THREADS='2')
    results = {'created_utc': datetime.now(timezone.utc).isoformat(),
               'manifest_sha256': digest(args.manifest), 'sources': manifest['sources'],
               'binary_sha256': digest(binary), 'normalizer_sha256': digest(args.normalizer),
               'cargo_lock_sha256': digest(ROOT / 'Cargo.lock'),
               'runner_sha256': digest(Path(__file__)), 'python_version': platform.python_version(),
               'poppler_version': subprocess.run(['pdftotext', '-v'], capture_output=True, text=True).stderr.strip(),
               'font_sha256': {p.name: digest(p) for p in sorted((bundle / 'fonts').glob('*.ttf'))},
               'git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
                   if (ROOT / '.git/HEAD').exists() and subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT, capture_output=True).returncode == 0 else None,
               'platform': platform.platform(), 'timeout_seconds': args.timeout,
               'preview_pages': args.preview_pages, 'reference_fonts': 'bundled Liberation only',
               'libreoffice_version': subprocess.check_output(['libreoffice', '--version'], text=True).strip() if args.reference else None,
               'fixtures': [], 'summary': {}}
    for fixture in selected:
        item = dict(fixture)
        source = (HERE / 'files' / fixture['file']).resolve()
        job = output / fixture['id']
        work = job / 'davros'
        pdf = work / 'preview.pdf'
        item['davros'] = run([binary, source, pdf], work, args.timeout, env)
        metrics = pdf_metrics(pdf)
        if metrics:
            item['davros']['pdf'] = metrics
        success = item['davros']['exit_code'] == 0 and metrics and 'pages' in metrics
        if fixture['expect'] == 'reject':
            item['status'] = ('expected_rejection' if item['davros']['exit_code'] > 0
                              and not item['davros']['timeout'] and not pdf.exists() else 'unexpected_acceptance_or_crash')
        else:
            item['status'] = ('converted' if success else 'timeout' if item['davros']['timeout']
                              else 'crashed' if item['davros']['exit_code'] < 0 else 'conversion_failed')
        stage_pdfs = {'davros': pdf}
        if args.reference and fixture['expect'] == 'render':
            refwork = job / 'reference'
            item['reference'] = run(libreoffice(source, refwork, bundle), refwork, args.timeout)
            refpdf = refwork / 'input.pdf'
            refmetrics = pdf_metrics(refpdf)
            if refmetrics:
                item['reference']['pdf'] = refmetrics
            stage_pdfs['reference'] = refpdf
            if source.suffix in LEGACY:
                normwork = job / 'normalization'
                item['normalization'] = run([args.normalizer.resolve(), source, normwork], normwork, args.timeout, env)
                normalized = normwork / ('normalized' + LEGACY[source.suffix])
                if item['normalization']['exit_code'] == 0 and normalized.exists():
                    normref = job / 'normalized_reference'
                    item['normalized_reference'] = run(libreoffice(normalized, normref, bundle), normref, args.timeout)
                    normpdf = normref / 'input.pdf'
                    normmetrics = pdf_metrics(normpdf)
                    if normmetrics:
                        item['normalized_reference']['pdf'] = normmetrics
                    stage_pdfs['normalized_reference'] = normpdf
        for key, stage_pdf in stage_pdfs.items():
            stage = item[key]
            stage['valid_pdf'] = stage['exit_code'] == 0 and 'pages' in stage.get('pdf', {})
            try:
                stage['previews'] = [str(p.relative_to(output)) for p in preview(stage_pdf, stage.get('pdf'), args.preview_pages)]
            except subprocess.SubprocessError as error:
                stage['previews'] = []
                stage['preview_error'] = str(error)
        for label, actual, reference in [('comparison', 'davros', 'reference'),
                                         ('normalization_comparison', 'normalized_reference', 'reference'),
                                         ('renderer_comparison', 'davros', 'normalized_reference')]:
            if all(item.get(k, {}).get('valid_pdf') for k in (actual, reference)):
                item[label] = compare(stage_pdfs[actual], stage_pdfs[reference])
        results['fixtures'].append(item)
        results['summary'] = dict(Counter(f['status'] for f in results['fixtures']))
        if args.reference:
            results['summary']['reference_failures'] = sum(not f['reference']['valid_pdf'] for f in results['fixtures'] if 'reference' in f)
            results['summary']['normalized_reference_failures'] = sum(not f['normalized_reference']['valid_pdf'] for f in results['fixtures'] if 'normalized_reference' in f)
        write_report(results, output)
        print(f"{fixture['id']}: {item['status']} ({item['davros']['seconds']}s, {item['davros']['peak_rss_mib']} MiB)", flush=True)
    print(output / 'report.html')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=HERE / 'manifest.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('fetch')
    ev = sub.add_parser('evaluate')
    ev.add_argument('--bundle', type=Path, default=ROOT / 'output/native-preview')
    ev.add_argument('--normalizer', type=Path, default=ROOT / 'target/release/examples/corpus-normalize')
    ev.add_argument('--output', type=Path, default=ROOT / 'tmp/corpus-evaluation')
    ev.add_argument('--reference', action='store_true')
    ev.add_argument('--timeout', type=float, default=60)
    ev.add_argument('--preview-pages', type=int, default=2)
    ev.add_argument('--ids', nargs='+')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    if args.command == 'fetch':
        fetch(manifest)
    else:
        evaluate(args, manifest)


if __name__ == '__main__':
    main()
