#!/usr/bin/env python3
"""Compare document previews with sandboxed LibreOffice references."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORPUS = ROOT / 'tests/corpus'
sys.path.insert(0, str(CORPUS))
sys.path.insert(0, str(HERE))
import run as corpus
from share import export_report
import native_fixtures

ODF = {'.docx': '.odt', '.xlsx': '.ods', '.pptx': '.odp'}
LABELS = {'reference': 'LibreOffice reference', 'davros': 'Current Davros',
          'candidate': 'libreoffice-rs direct', 'hybrid': 'Office Oxide → libreoffice-rs'}


def inspect(pdf):
    metrics = corpus.pdf_metrics(pdf)
    if not metrics or 'pages' not in metrics:
        return metrics
    listing = subprocess.check_output(['pdfimages', '-list', str(pdf)], text=True, timeout=20)
    pdf.with_suffix('.images.txt').write_text(listing)
    metrics['image_objects'] = sum('image' in line.split() for line in listing.splitlines()[2:])
    fonts = subprocess.check_output(['pdffonts', str(pdf)], text=True, timeout=20)
    pdf.with_suffix('.fonts.txt').write_text(fonts)
    # Poppler text extraction can retain words positioned outside the page.
    bbox = subprocess.check_output(['pdftotext', '-bbox', str(pdf), '-'], timeout=20)
    pdf.with_suffix('.bbox.html').write_bytes(bbox)
    try:
        root = ET.fromstring(bbox)
        outside = []
        for page in root.iter('{http://www.w3.org/1999/xhtml}page'):
            width, height = float(page.get('width')), float(page.get('height'))
            for word in page.iter('{http://www.w3.org/1999/xhtml}word'):
                if (float(word.get('xMin')) < -1 or float(word.get('yMin')) < -1
                    or float(word.get('xMax')) > width + 1 or float(word.get('yMax')) > height + 1):
                    outside.append(word.text)
        metrics['off_page_words'] = len(outside)
        metrics['off_page_words_sample'] = outside[:20]
    except (ET.ParseError, ValueError, TypeError) as error:
        metrics['bbox_error'] = str(error)
    return metrics


def summarize(records):
    summary = {}
    for ext in sorted({r['extension'] for r in records}):
        group = [r for r in records if r['extension'] == ext]
        summary[ext] = {}
        for stage in LABELS:
            values = [r[stage] for r in group if stage in r and r['expect'] == 'render']
            recalls = [v['comparison']['token_recall'] for v in values
                       if v.get('comparison', {}).get('token_recall') is not None]
            summary[ext][stage] = {
                'render_cases': len(values),
                'valid_pdfs': sum(v['valid_pdf'] for v in values),
                'statuses': dict(Counter(v['status'] for v in values)),
                'scored_cases': len(recalls),
                'mean_token_recall': round(statistics.mean(recalls), 4) if recalls else None,
                'median_seconds': round(statistics.median(v['seconds'] for v in values), 3) if values else None,
            }
    return summary


def compare_previews(candidate, reference, output):
    """Pixel diagnostics, including blank-text drawings; not a perceptual score."""
    from PIL import Image, ImageChops
    pages = []
    for actual, expected in zip(candidate['previews'], reference['previews']):
        with Image.open(output / actual) as a, Image.open(output / expected) as b:
            a, b = a.convert('RGB'), b.convert('RGB')
            same_size = a.size == b.size
            if not same_size:
                # Poppler rounds fractional page dimensions to whole pixels.
                # Pad a one-pixel discrepancy; never scale document contents.
                if any(abs(x-y) > 1 for x,y in zip(a.size, b.size)):
                    pages.append({'same_raster_size': False})
                    continue
                size = tuple(max(x,y) for x,y in zip(a.size,b.size))
                padded = Image.new('RGB', size, 'white'); padded.paste(a); a = padded
                padded = Image.new('RGB', size, 'white'); padded.paste(b); b = padded
            diff = ImageChops.difference(a, b)
            channels = diff.split()
            maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            mismatch = maximum.point(lambda v: 255 if v > 32 else 0)
            ink = ImageChops.darker(a.convert('L'), b.convert('L')).point(lambda v: 255 if v < 245 else 0)
            ink_count = ink.histogram()[255]
            differing = ImageChops.multiply(mismatch, ink).histogram()[255]
            pages.append(dict(same_raster_size=same_size, padded_rounding_pixel=not same_size, foreground_pixels=ink_count,
                              differing_foreground_fraction=round(differing / ink_count, 4) if ink_count else 0.0))
    return {'compared_pages': len(pages), 'pages': pages}


def report(results, output):
    results['summary'] = summarize(results['fixtures'])
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    esc = html.escape
    details, rows = [], []
    for item in results['fixtures']:
        panels = []
        for stage, label in LABELS.items():
            value = item.get(stage)
            if value is None:
                continue
            rel = f"{item['id']}/{stage}"
            links = f'<a href="{rel}/stderr.log">log</a>'
            if value['valid_pdf']:
                links += f' · <a href="{rel}/preview.pdf">PDF</a> · <a href="{rel}/preview.txt">text</a>'
            images = ''.join(f'<a href="{esc(p)}"><img loading="lazy" src="{esc(p)}"></a>' for p in value.get('previews', []))
            stats = {k: value[k] for k in ['status', 'seconds', 'pdf', 'comparison', 'visual_comparison', 'checks'] if k in value}
            panels.append(f'<div><h3>{label}</h3>{links}<pre>{esc(json.dumps(stats, indent=2))}</pre>{images}</div>')
        source_link = f'<a href="{esc(item["input_file"])}">Source document</a>' if 'input_file' in item else ''
        details.append(f'<section id="{item["id"]}"><h2>{esc(item["id"])}</h2>'
                       f'<p>{esc(item.get("purpose", ""))} {source_link}</p><div class="panels">{"".join(panels)}</div></section>')
        row = [f'<a href="#{item["id"]}">{esc(item["id"])}</a>']
        for stage in LABELS:
            value = item.get(stage, {})
            recall = value.get('comparison', {}).get('token_recall')
            row.append(esc(value.get('status', 'not tested')) + (f' · recall {recall:.1%}' if recall is not None else ''))
        rows.append('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>')
    document = '''<!doctype html><meta charset="utf-8"><title>libreoffice-rs comparison</title>
<style>body{font:15px system-ui;margin:24px;background:#eee;color:#222}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:7px}section{margin-top:36px}.panels{display:flex;gap:16px}.panels>div{flex:1;min-width:0}img{width:100%;background:white}pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1751a8}</style>
<h1>libreoffice-rs versus Davros</h1>
<p>Valid PDF ≠ correct preview. Word-multiset recall ignores order and layout; text outside the page may still be extracted. Image counts do not measure vector drawings. Pixel diagnostics count foreground pixels differing by more than 32/255 in any colour channel; font and antialiasing differences also count. They are not perceptual quality scores. Preview coverage is configurable; inspect full PDFs for unshown pages. Timing is a single local run, not a benchmark. ODF fixtures include exported controls, directly authored synthetic controls, and optional pinned upstream native regression documents; their origins are recorded in results.json.</p>
'''
    if 'assessment' in results:
        document += '<h2>Assessment</h2><ul>' + ''.join('<li>' + esc(v) + '</li>' for v in results['assessment']) + '</ul>'
    if 'sizes' in results:
        document += '<h2>Size measurements</h2><pre>' + esc(json.dumps(results['sizes'], indent=2)) + '</pre>'
    document += '<details><summary>Provenance and environment</summary><pre>' + esc(json.dumps(results['metadata'], indent=2)) + '</pre></details>'
    document += '<details><summary>Per-format totals</summary><pre>' + esc(json.dumps(results['summary'], indent=2)) + '</pre></details>'
    document += '<table><tr><th>Fixture</th>' + ''.join(f'<th>{v}</th>' for v in LABELS.values()) + '</tr>'
    (output / 'report.html').write_text(document + ''.join(rows) + '</table>' + ''.join(details))


def checks(record, pdf):
    text = pdf.with_suffix('.txt').read_text()
    result = {}
    if record['id'] == 'native-writer':
        result['nested_list_content'] = all(s in text for s in ['First paragraph', 'Second paragraph', 'Nested item'])
        result['page_headers'] = all(s in text for s in ['First page header', 'Later page header'])
        result['page_fields'] = all(s in text for s in ['Page 1 of 2', 'Page 2 of 2'])
        result['image_present'] = inspect_image_count(pdf) >= 1
    if record['id'] == 'native-impress':
        result['image_present'] = inspect_image_count(pdf) >= 1
        result['nested_list_content'] = 'Outer item' in text and 'Nested item' in text
        result['mixed_text_order'] = 'Before middle after' in text
    if record['id'] == 'native-calc':
        result['header_rows'] = 'Native ODS control' in text
        result['display_values'] = all(s in text for s in ['12.5%', '-$12.50', '29-Feb-2024'])
        result['hidden_sheet_omitted'] = 'Hidden sentinel' not in text
        result['repeated_rows'] = text.count('Repeated row') == 2
        result['merged_and_wrapped_content'] = all(s in text for s in ['Merged cell', 'Tail cell', 'Wrapped', 'within cell'])
    if record['id'].startswith('synthetic-') or record['id'].startswith('odf-synthetic-'):
        compact = ''.join(text.split())
        result['selectable_text'] = 'Selectablepreviewtext' in compact
        if record['extension'] in ('.xls', '.xlsx', '.ods'):
            result['percentage'] = '12.5%' in text and '13.0%' not in text
            result['currency'] = '$12.50' in text and '$12.500' not in text
            result['last_row'] = 'Selectablepreviewtext205' in compact
    if record['id'] == 'poi-word-PngPicture-doc':
        result['image_present'] = inspect_image_count(pdf) > 0
    if record['id'] == 'poi-word-footnote-doc':
        result['footnote_body'] = 'TestFootnote' in text
        result['endnote_body'] = 'TestEndnote' in text
        result['comment_not_body'] = 'TestComment' not in text
    if record['id'] == 'poi-word-DiffFirstPageHeadFoot-doc':
        pages = text.split('\f')
        result['two_pages'] = len(pages) - 1 == 2
        result['distinct_page_content'] = ('End of page 1' in pages[0] and 'This is page two' not in pages[0]
                                           and len(pages) > 1 and 'This is page two' in pages[1])
    if record['id'] == 'poi-excel-DateFormats-xls':
        result['distinct_dates'] = all(s in text for s in ['10-Aug-07', '8/10/07', '10/08/07'])
    return result


def inspect_image_count(pdf):
    return sum('image' in line.split() for line in pdf.with_suffix('.images.txt').read_text().splitlines()[2:])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--bundle', type=Path, default=ROOT / 'output/native-preview')
    p.add_argument('--normalizer', type=Path, default=ROOT / 'target/release/examples/corpus-normalize')
    p.add_argument('--timeout', type=float, default=60)
    p.add_argument('--build-info', type=Path, help='Optional candidate build provenance JSON')
    p.add_argument('--odf-only', action='store_true', help='Evaluate ODT, ODS and ODP controls only')
    p.add_argument('--native-corpus', type=Path, help='Additional pinned native ODF corpus manifest')
    p.add_argument('--preview-pages', type=int, default=2)
    args = p.parse_args()
    output, bundle, candidate, normalizer = [v.resolve() for v in [args.output, args.bundle, args.candidate, args.normalizer]]
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new or empty output directory')
    for binary in [candidate, normalizer, bundle / 'davros-preview']:
        if not binary.is_file(): raise ValueError(f'Missing binary: {binary}')
    manifest = json.loads((CORPUS / 'manifest.json').read_text())
    corpus.validate_manifest(manifest)
    fixtures = []
    for record in manifest['fixtures']:
        source = CORPUS / 'files' / record['file']
        corpus.verified(source, record)
        fixtures.append(dict(record, source_path=str(source), extension=source.suffix, origin='public corpus'))
    for source in sorted((ROOT / 'tests/fixtures').iterdir()):
        fixtures.append(dict(id='synthetic-' + source.name.replace('.', '-'), source_path=str(source),
                             extension=source.suffix, expect='render', sha256=corpus.digest(source), origin='synthetic'))
    output.mkdir(parents=True, exist_ok=True)
    command = corpus.libreoffice(Path(fixtures[0]['source_path']), output / 'preflight', bundle)
    command = command[:command.index('/usr/bin/libreoffice') + 1] + ['--version']
    preflight = corpus.run(command, output / 'preflight', args.timeout)
    if preflight['exit_code']:
        raise RuntimeError('Reference sandbox unavailable: ' + preflight['stderr_tail'])
    env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'), FONTCONFIG_FILE=str(bundle / 'fonts.conf'),
               RAYON_NUM_THREADS='2', LIBREOFFICE_PURE_UNICODE_FONT=os.pathsep.join(str(p) for p in sorted((bundle / 'fonts').glob('*.ttf'))))
    # Six public modern controls and the three basic synthetic documents become
    # ODF controls. Preserve exporter logs, generated bytes and hashes.
    for record in list(fixtures):
        if record['extension'] not in ODF or (record['origin'] == 'synthetic' and not record['id'].startswith('synthetic-basic-')):
            continue
        source = Path(record['source_path'])
        target_ext = ODF[source.suffix]
        work = output / 'odf-generation' / record['id']
        command = corpus.libreoffice(source, work, bundle)
        command[command.index('--convert-to') + 1] = target_ext[1:]
        generation = corpus.run(command, work, args.timeout)
        target = work / ('input' + target_ext)
        (work / 'generation.json').write_text(json.dumps(generation, indent=2))
        if generation['exit_code'] or not target.is_file():
            raise RuntimeError(f'ODF generation failed: {record["id"]}')
        fixtures.append(dict(id='odf-' + record['id'], source_path=str(target), extension=target_ext,
                             expect='render', sha256=corpus.digest(target), origin='LibreOffice-generated ODF control',
                             derived_from=record['id'], purpose='ODF export of ' + record['id']))
    for source in native_fixtures.build(output / 'native-inputs'):
        fixtures.append(dict(id=source.stem, source_path=str(source), extension=source.suffix,
                             expect='render', sha256=corpus.digest(source), origin='directly authored synthetic ODF',
                             purpose='Native ODF structure, style and content regression control'))
    if args.odf_only:
        fixtures = [record for record in fixtures if record['extension'] in ODF.values()]
    if args.native_corpus:
        native = json.loads(args.native_corpus.read_text())
        corpus.validate_manifest(native)
        ids = {record['id'] for record in fixtures}
        for record in native['fixtures']:
            source = CORPUS / 'files' / record['file']
            corpus.verified(source, record)
            if source.suffix not in ODF.values() or record['id'] in ids:
                raise ValueError('Expected unique native ODF fixture: ' + record['id'])
            ids.add(record['id'])
            fixtures.append(dict(record, source_path=str(source), extension=source.suffix,
                                 origin='upstream native ODF regression corpus'))
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                    scope='ODF only' if args.odf_only else 'all formats',
                    native_generator_sha256=corpus.digest(Path(native_fixtures.__file__)),
                    upstream_revision='291b94ae0083ccb2e5f2cf49b46626e41eedf53d',
                    git_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    candidate_sha256=corpus.digest(candidate), candidate_bytes=candidate.stat().st_size,
                    davros_sha256=corpus.digest(bundle / 'davros-preview'), davros_bytes=(bundle / 'davros-preview').stat().st_size,
                    normalizer_sha256=corpus.digest(normalizer), runner_sha256=corpus.digest(Path(__file__)),
                    shared_runner_sha256=corpus.digest(CORPUS / 'run.py'), manifest_sha256=corpus.digest(CORPUS / 'manifest.json'),
                    font_sha256={p.name: corpus.digest(p) for p in sorted((bundle / 'fonts').glob('*.ttf'))},
                    libreoffice_version=(output / 'preflight/stdout.log').read_text().strip(),
                    fonts='Same bundled Liberation files; candidate uses built-in PDF base fonts for Latin text',
                    timeout_seconds=args.timeout)
    results = dict(metadata=metadata, fixtures=[])
    if args.native_corpus:
        metadata['native_corpus'] = native
        metadata['native_corpus_sha256'] = corpus.digest(args.native_corpus)
    if args.build_info:
        metadata['candidate_build'] = json.loads(args.build_info.read_text())
    for record in fixtures:
        source = Path(record['source_path'])
        item = dict(record)
        copied = output / 'inputs' / (record['id'] + record['extension'])
        copied.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, copied)
        item['input_file'] = str(copied.relative_to(output))
        job = output / record['id']
        stages = ['candidate']
        if record['extension'] not in ODF.values(): stages.insert(0, 'davros')
        if record['expect'] == 'render': stages.insert(0, 'reference')
        if source.suffix in corpus.LEGACY and record['expect'] == 'render':
            normwork = job / 'normalization'
            item['normalization'] = corpus.run([normalizer, source, normwork], normwork, args.timeout, env)
            normalized = normwork / ('normalized' + corpus.LEGACY[source.suffix])
            if item['normalization']['exit_code'] == 0 and normalized.exists(): stages.append('hybrid')
        for stage in stages:
            work = job / stage
            pdf = work / 'preview.pdf'
            if stage == 'reference': command = corpus.libreoffice(source, work, bundle)
            else: command = [bundle / 'davros-preview' if stage == 'davros' else candidate,
                             normalized if stage == 'hybrid' else source, pdf]
            value = corpus.run(command, work, args.timeout, env)
            if stage == 'reference' and (work / 'input.pdf').exists():
                (work / 'input.pdf').rename(pdf)
            metrics = inspect(pdf)
            if metrics: value['pdf'] = metrics
            value['valid_pdf'] = bool(value['exit_code'] == 0 and metrics and 'pages' in metrics)
            value['status'] = ('converted' if value['valid_pdf'] else 'timeout' if value['timeout'] else
                               'crashed' if value['exit_code'] < 0 else 'conversion_failed')
            if record['expect'] == 'reject':
                value['status'] = ('expected_rejection' if value['exit_code'] > 0 and not value['timeout'] and not pdf.exists()
                                   else 'unexpected_acceptance_or_crash')
            value['previews'] = [str(p.relative_to(output)) for p in corpus.preview(pdf, metrics, args.preview_pages)] if value['valid_pdf'] else []
            if value['valid_pdf']:
                value['checks'] = checks(record, pdf)
                if stage != 'reference' and item.get('reference', {}).get('valid_pdf'):
                    value['comparison'] = corpus.compare(pdf, job / 'reference/preview.pdf')
                    value['visual_comparison'] = compare_previews(value, item['reference'], output)
            item[stage] = value
        results['fixtures'].append(item)
        report(results, output)
        print(record['id'] + ': ' + ', '.join(f'{s}={item[s]["status"]}' for s in stages), flush=True)
    # Publish a small review bundle rather than the reference engine's profiles,
    # font caches and intermediate outputs. Carry fixture redistribution notices.
    licenses = CORPUS / 'licenses'
    if licenses.is_dir():
        shutil.copytree(licenses, output / 'source-licenses', dirs_exist_ok=True)
    directory, archive, count = export_report(output, output.with_name(output.name + '-share'))
    print(f'{directory / "report.html"} ({count} files)')
    print(archive)


if __name__ == '__main__':
    main()
