#!/usr/bin/env python3
"""Exercise the packaged binary; only Python stdlib and Poppler are needed."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
bundle = root / 'output/native-preview'
binary = bundle / 'davros-preview'
env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
           FONTCONFIG_FILE=str(bundle / 'fonts.conf'), RAYON_NUM_THREADS='2')
texts = {}
with tempfile.TemporaryDirectory(prefix='davros-preview-tests-') as tmp:
    for source in sorted((root / 'tests/fixtures').iterdir()):
        scratch = Path(tmp) / source.name
        scratch.mkdir()
        pdf = scratch / 'preview.pdf'
        subprocess.run([binary, source, pdf], env=env, check=True, timeout=60)
        assert pdf.read_bytes().startswith(b'%PDF-'), source
        # Legacy XLS preserves the fixture's narrow columns. Poppler's layout
        # heuristics interleave adjacent cells; raw order tests text retention
        # independently of the documented legacy layout limitations.
        text_options = ['-raw'] if source.suffix == '.xls' else []
        text = subprocess.check_output(['pdftotext', *text_options, str(pdf), '-'], text=True)
        texts[source.name] = text
        assert 'Selectablepreviewtext' in re.sub(r'\s', '', text), source
        assert not list(scratch.glob('davros-legacy-*')), source
        if source.suffix in ('.xls', '.xlsx'):
            assert '12.5%' in text and '13.0%' not in text, source
            assert '$12.50' in text and '$12.500' not in text, source
        if source.suffix == '.xls':
            compact = re.sub(r'\s', '', text)
            for row in range(1, 206):
                assert f'Selectablepreviewtext{row}12.5%' in compact, row
        if source.stem == 'wide':
            pages = text.split('\f')
            first = re.sub(r'\s', '', pages[0])
            assert 'Sharednamespacevalue' in first and 'Selectablepreviewtext1' in first
            assert 'Selectablepreviewtext205' not in first
            assert 'Selectablepreviewtext205' in re.sub(r'\s', '', ''.join(pages[1:]))
            info = subprocess.check_output(['pdfinfo', str(pdf)], text=True)
            size = re.search(r'Page size:\s+([\d.]+) x ([\d.]+)', info)
            assert size and float(size[1]) > 1500 and float(size[2]) < 900
        print('PASS:', source.name)
    for prefix in ['x', 'spreadsheet']:
        assert texts[f'prefixed-{prefix}.xlsx'] == texts['basic.xlsx']
    for ext in ('doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'):
        bad = Path(tmp) / f'malformed.{ext}'
        scratch = Path(tmp) / f'invalid-{ext}'
        scratch.mkdir()
        output = scratch / 'preview.pdf'
        for kind in ('malformed', 'oversized', 'renamed-zip'):
            if kind == 'renamed-zip' and ext.endswith('x'):
                continue
            if kind == 'oversized':
                with bad.open('wb') as f:
                    f.truncate(32 * 1024 * 1024 + 1)
            elif kind == 'renamed-zip':
                bad.write_bytes((root / 'tests/fixtures' / f'basic.{ext}x').read_bytes())
            else:
                bad.write_bytes(b'not an Office document')
            failure = subprocess.run([binary, bad, output], env=env,
                                     capture_output=True, timeout=60)
            assert failure.returncode and not output.exists(), (ext, kind)
            assert not list(scratch.glob('davros-legacy-*')), (ext, kind)
            if kind == 'oversized':
                assert b'Document exceeds 32 MiB' in failure.stderr, failure.stderr
            print(f'PASS: {kind} {ext} rejected without a PDF')

    # Extension handling must be case-insensitive for documents uploaded from Windows.
    for ext in ('DOC', 'DOCX', 'XLS', 'XLSX', 'PPT', 'PPTX'):
        source = Path(tmp) / f'uppercase.{ext}'
        source.write_bytes((root / 'tests/fixtures' / f'basic.{ext.lower()}').read_bytes())
        scratch = Path(tmp) / f'uppercase-{ext}'
        scratch.mkdir()
        subprocess.run([binary, source, scratch / 'preview.pdf'], env=env, check=True, timeout=60)
        assert (scratch / 'preview.pdf').read_bytes().startswith(b'%PDF-')
        assert not list(scratch.glob('davros-legacy-*'))
        print(f'PASS: uppercase {ext}')

    for ext in ('doc', 'xls', 'ppt'):
        source = root / 'tests/fixtures' / f'basic.{ext}'
        scratch = Path(tmp) / f'failed-render-{ext}'
        scratch.mkdir()
        # A directory at the PDF path forces rendering/output to fail after
        # successful legacy normalization, exercising intermediate cleanup.
        output = scratch / 'preview.pdf'
        output.mkdir()
        failure = subprocess.run([binary, source, output], env=env,
                                 capture_output=True, timeout=60)
        assert failure.returncode and output.is_dir(), ext
        assert not list(scratch.glob('davros-legacy-*')), ext
        print(f'PASS: {ext} intermediate removed after output failure')

    for name in ('unsupported.pdf', 'unsupported.txt', 'missing-extension'):
        scratch = Path(tmp) / f'invalid-format-{name}'
        scratch.mkdir()
        source = Path(tmp) / name
        source.write_bytes((root / 'tests/fixtures/basic.docx').read_bytes())
        output = scratch / 'preview.pdf'
        failure = subprocess.run([binary, source, output], env=env,
                                 capture_output=True, timeout=60)
        assert failure.returncode and b'Supported input formats' in failure.stderr
        assert not output.exists()
        print(f'PASS: rejects {name}')

    failure = subprocess.run([binary], env=env, capture_output=True, timeout=60)
    assert failure.returncode and b'usage: davros-preview' in failure.stderr
    print('PASS: usage error')
