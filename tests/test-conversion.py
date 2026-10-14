#!/usr/bin/env python3
"""Exercise the packaged binary; only Python stdlib and Poppler are needed."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parent.parent
bundle = root / 'output/native-preview'
binary = bundle / 'davros-preview'
env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
           FONTCONFIG_FILE=str(bundle / 'fonts.conf'), RAYON_NUM_THREADS='2')
texts = {}
sys.path.insert(0, str(root / 'tests/corpus/odf'))
from native_fixtures import build as build_odf, package as package_odf

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
    odf_sources = build_odf(Path(tmp) / 'odf-inputs')
    for source in odf_sources:
        for uppercase in (False, True):
            original = source
            if uppercase:
                source = original.with_suffix(original.suffix.upper())
                source.write_bytes(original.read_bytes())
            scratch = Path(tmp) / source.name
            scratch.mkdir()
            pdf = scratch / 'preview.pdf'
            subprocess.run([binary, source, pdf], env=env, check=True, timeout=60)
            text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
            assert f'Native {source.suffix[1:].upper()} control' in text, text
            if source.suffix.lower() == '.odt':
                assert 'First page header' in text and 'Later page header' in text
                assert 'Page 1 of 2' in text and 'Page 2 of 2' in text
            elif source.suffix.lower() == '.ods':
                assert '12.5%' in text and '-$12.50' in text and '29-Feb-2024' in text
                assert 'Hidden sentinel' not in text
            else:
                assert 'Before middle after' in text and 'Nested item' in text
            assert sorted(p.name for p in scratch.iterdir()) == ['preview.pdf']
            print('PASS:', source.name)

    # Native enhanced geometry must survive the production SVG feature/dispatch.
    shapes_source = Path(tmp) / 'shapes.odp'
    package_odf(shapes_source, 'presentation', '<office:presentation><draw:page draw:name="Shapes"><draw:custom-shape svg:x="1in" svg:y="1in" svg:width="1in" svg:height="1in"><draw:enhanced-geometry draw:enhanced-path="U 10800 10800 10800 10800 0 360 Z U 10800 10800 5400 5400 0 360 Z N"/></draw:custom-shape><draw:frame svg:x="1in" svg:y="3in" svg:width="5in" svg:height="1in"><draw:text-box><text:p text:style-name="Both">Bold italic selectable text</text:p></draw:text-box></draw:frame></draw:page></office:presentation>',
                automatic='<style:style style:name="Both" style:family="paragraph"><style:text-properties fo:font-family="Liberation Sans" fo:font-weight="bold" fo:font-style="italic"/></style:style>')
    scratch = Path(tmp) / 'shapes-output'
    scratch.mkdir()
    pdf = scratch / 'preview.pdf'
    subprocess.run([binary, shapes_source, pdf], env=env, check=True, timeout=60)
    text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
    assert 'Bold italic selectable text' in text
    assert re.search(rb'/F8 [0-9.]+ Tf', pdf.read_bytes())
    assert b'Helvetica-BoldOblique' in pdf.read_bytes()
    images = subprocess.check_output(['pdfimages', '-list', str(pdf)], text=True)
    assert any('image' in line.split() for line in images.splitlines()[2:]), images
    print('PASS: enhanced ODF geometry and selectable bold italic text')

    # Exercise embedded Unicode fonts inside Landlock, not just PDF base fonts.
    unicode_source = Path(tmp) / 'unicode.odt'
    package_odf(unicode_source, 'text', '<office:text><text:p>Greek αβγ Cyrillic Привет</text:p></office:text>')
    scratch = Path(tmp) / 'unicode-output'
    scratch.mkdir()
    pdf = scratch / 'preview.pdf'
    unicode_env = dict(env, LIBREOFFICE_PURE_UNICODE_FONT='/nonexistent/font.ttf')
    subprocess.run([binary, unicode_source, pdf], env=unicode_env, check=True, timeout=60)
    text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
    assert 'αβγ' in text and 'Привет' in text, text
    print('PASS: bundled Unicode fonts override upstream font discovery')

    for ext in ('doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp'):
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
                fixture = f'basic.{ext}x' if ext in ('doc', 'xls', 'ppt') else 'basic.docx'
                bad.write_bytes((root / 'tests/fixtures' / fixture).read_bytes())
            else:
                bad.write_bytes(b'not an Office document')
            failure = subprocess.run([binary, bad, output], env=env,
                                     capture_output=True, timeout=60)
            assert failure.returncode and not output.exists(), (ext, kind)
            assert not list(scratch.glob('davros-legacy-*')), (ext, kind)
            if kind == 'oversized':
                assert b'Document exceeds 32 MiB' in failure.stderr, failure.stderr
            print(f'PASS: {kind} {ext} rejected without a PDF')

    # ODF packages use the same decompression preflight as OOXML.
    for ext in ('odt', 'ods', 'odp'):
        source = Path(tmp) / f'expanded.{ext}'
        with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('content.xml', b' ' * (32 * 1024 * 1024 + 1))
        scratch = Path(tmp) / f'expanded-{ext}'
        scratch.mkdir()
        pdf = scratch / 'preview.pdf'
        failure = subprocess.run([binary, source, pdf], env=env, capture_output=True, timeout=60)
        assert failure.returncode and b'Archive entry exceeds' in failure.stderr
        assert not pdf.exists()
        print(f'PASS: oversized decompression {ext}')

    # Tiny documents must not expand into enormous trees or repeated sheets.
    bombs = [
        ('nested', 'odt', 'text', '<office:text>' + '<text:span>' * 80 + 'x' + '</text:span>' * 80 + '</office:text>', b'XML expansion'),
        ('repeated', 'ods', 'spreadsheet', '<office:spreadsheet><table:table><table:table-row table:number-rows-repeated="1000000"><table:table-cell table:number-columns-repeated="16384" office:value-type="float" office:value="1"/></table:table-row></table:table></office:spreadsheet>', b'expanded cells'),
    ]
    for name, ext, family, body, diagnostic in bombs:
        source = Path(tmp) / f'bomb-{name}.{ext}'
        package_odf(source, family, body)
        scratch = Path(tmp) / f'bomb-{name}'
        scratch.mkdir()
        pdf = scratch / 'preview.pdf'
        failure = subprocess.run([binary, source, pdf], env=env, capture_output=True, timeout=10)
        assert failure.returncode and diagnostic in failure.stderr, (name, failure.stderr)
        assert not pdf.exists()
        print(f'PASS: {name} expansion rejected before rendering')

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
