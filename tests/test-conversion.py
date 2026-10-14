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

    # Writer outline wrappers and joined code boxes, without a network fixture.
    writer_source = Path(tmp) / 'writer-template.odt'
    package_odf(writer_source, 'text',
                '<office:text><text:h text:outline-level="1">Introduction</text:h>'
                '<text:list><text:list-item><text:h text:outline-level="2">Model</text:h></text:list-item></text:list>'
                '<text:p text:style-name="Code">CREATE TABLE</text:p>'
                '<text:p text:style-name="Code"><text:s text:c="4"/>country_id uuid,</text:p></office:text>',
                automatic='<style:style style:name="Code" style:family="paragraph"><style:paragraph-properties fo:background-color="#fff5e0" fo:border="0.5pt solid #ff0000" fo:padding="2pt"/><style:text-properties fo:font-family="Liberation Mono" fo:font-size="10pt"/></style:style>',
                styles='<text:outline-style><text:outline-level-style text:level="1" style:num-format="1"/><text:outline-level-style text:level="2" style:num-format="1" text:display-levels="2"/></text:outline-style>')
    writer_output = Path(tmp) / 'writer-output'
    writer_output.mkdir()
    writer_pdf = writer_output / 'preview.pdf'
    subprocess.run([binary, writer_source, writer_pdf], env=env, check=True, timeout=60)
    text = subprocess.check_output(['pdftotext', '-layout', str(writer_pdf), '-'], text=True)
    compact = ''.join(text.split())
    assert '1Introduction' in compact and '1.1Model' in compact, text
    assert re.search(r'^ +country_id uuid,', text, re.MULTILINE), text
    assert text.count('\f') == 1
    # Solid borders use stroke colors; paragraph fills are PDF rectangles.
    assert b'1.000 0.000 0.000 RG' in writer_pdf.read_bytes()
    assert b're f' in writer_pdf.read_bytes()
    print('PASS: Writer outline headings, explicit spaces and paragraph boxes')

    # A cover master and heading page break must produce two pages, with no
    # spurious first page and no normal footer painted on the cover.
    cover_source = Path(tmp) / 'cover-layout.odt'
    package_odf(cover_source, 'text',
                '<office:text><text:p text:style-name="Start">Cover sentinel</text:p>'
                '<text:h text:style-name="Chapter" text:outline-level="1">Introduction sentinel</text:h>'
                '<text:p text:style-name="Body">Fractional size sentinel</text:p>'
                '<text:p text:style-name="Code"><text:s text:c="4"/>CONFIG_MTD=y<text:s text:c="63"/></text:p></office:text>',
                automatic='<style:style style:name="Start" style:family="paragraph" style:master-page-name="Cover"><style:paragraph-properties fo:break-before="page"/></style:style>'
                '<style:style style:name="Chapter" style:family="paragraph"><style:paragraph-properties fo:break-before="page"/></style:style>'
                '<style:style style:name="Body" style:family="paragraph"><style:text-properties fo:font-size="10.5pt"/></style:style>'
                '<style:style style:name="Code" style:family="paragraph"><style:text-properties fo:font-size="10pt" fo:font-family="Liberation Mono"/></style:style>',
                master='<style:footer><text:p>Body footer sentinel</text:p></style:footer>')
    with zipfile.ZipFile(cover_source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries['styles.xml'] = entries['styles.xml'].replace(b'</office:master-styles>',
        b'<style:master-page style:name="Cover" style:page-layout-name="Page" style:next-style-name="Standard"><style:footer><text:p/></style:footer></style:master-page></office:master-styles>')
    with zipfile.ZipFile(cover_source, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    cover_output = Path(tmp) / 'cover-output'
    cover_output.mkdir()
    cover_pdf = cover_output / 'preview.pdf'
    subprocess.run([binary, cover_source, cover_pdf], env=env, check=True, timeout=60)
    text = subprocess.check_output(['pdftotext', str(cover_pdf), '-'], text=True)
    pages = text.split('\f')
    assert len(pages) == 3, text
    assert 'Cover sentinel' in pages[0] and 'Introduction sentinel' not in pages[0]
    assert 'Body footer sentinel' not in pages[0] and 'Body footer sentinel' in pages[1]
    assert 'Introduction sentinel' in pages[1] and 'CONFIG_MTD=y' in pages[1]
    assert re.search(rb'/F[0-9]+ 10\.50? Tf', cover_pdf.read_bytes())
    print('PASS: cover master, heading break, fractional font sizes and padded code')

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
    package_odf(unicode_source, 'text', '<office:text><text:p>Greek αβγ Cyrillic Привет</text:p><text:p>Triangular bullet ‣ Kernel lab</text:p></office:text>')
    scratch = Path(tmp) / 'unicode-output'
    scratch.mkdir()
    pdf = scratch / 'preview.pdf'
    unicode_env = dict(env, LIBREOFFICE_PURE_UNICODE_FONT='/nonexistent/font.ttf')
    subprocess.run([binary, unicode_source, pdf], env=unicode_env, check=True, timeout=60)
    text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
    assert 'αβγ' in text and 'Привет' in text, text
    assert 'Triangular bullet ‣ Kernel lab' in text, text
    fonts = subprocess.check_output(['pdffonts', str(pdf)], text=True)
    assert 'NotoSans' in fonts, fonts
    print('PASS: bundled Unicode fonts override upstream font discovery')

    # Private-use characters absent from our fonts: distinct BMP and astral
    # characters must remain distinct when copied, including repeated glyphs.
    missing = "\ue000\ue001\U000f0000\ue000"
    label = f"Before {missing} after α ‣"
    tofu_bodies = {
        'odt': ('text', f'<office:text><text:p>{label}</text:p></office:text>'),
        'ods': ('spreadsheet', '<office:spreadsheet><table:table table:name="Tofu">'
                '<table:table-row><table:table-cell office:value-type="string">'
                f'<text:p>{label}</text:p></table:table-cell></table:table-row>'
                '</table:table></office:spreadsheet>'),
        'odp': ('presentation', '<office:presentation><draw:page draw:name="Tofu">'
                '<draw:frame svg:x="1cm" svg:y="1cm" svg:width="20cm" svg:height="3cm">'
                f'<draw:text-box><text:p>{label}</text:p></draw:text-box>'
                '</draw:frame></draw:page></office:presentation>'),
    }
    for ext, (kind, body) in tofu_bodies.items():
        source = Path(tmp) / f'tofu.{ext}'
        package_odf(source, kind, body)
        scratch = Path(tmp) / f'tofu-{ext}-output'
        scratch.mkdir()
        pdf = scratch / 'preview.pdf'
        result = subprocess.run([binary, source, pdf], env=env, capture_output=True,
                                text=True, check=True, timeout=60)
        assert 'rendering 3 unsupported Unicode characters as boxes' in result.stderr, result.stderr
        text = subprocess.check_output(['pdftotext', '-raw', str(pdf), '-'], text=True)
        assert label in text, (ext, text)
        data = pdf.read_bytes()
        assert b'LOTOFU+MissingGlyph' in data
        # All three CIDs draw the same nonzero square glyph, while ToUnicode
        # preserves the distinct original characters (including a surrogate pair).
        mapping_ref = re.search(rb'/CIDToGIDMap (\d+) 0 R', data)
        assert mapping_ref, ext
        mapping = re.search(rb'\b' + mapping_ref[1] +
                            rb' 0 obj\s*<< /Length 8 >>\s*stream\n(.{8})', data, re.S)
        assert mapping and mapping[1][:2] == b'\x00\x00', ext
        assert mapping[1][2:4] == mapping[1][4:6] == mapping[1][6:8] != b'\x00\x00'
        for value in (b'<0001> <E000>', b'<0002> <E001>', b'<0003> <DB80DC00>'):
            assert value in data, (ext, value)
        subprocess.run(['pdftoppm', '-f', '1', '-singlefile', '-scale-to', '600',
                        '-png', str(pdf), str(scratch / 'render')],
                       check=True, capture_output=True, timeout=60)
        assert (scratch / 'render.png').stat().st_size > 1000
        print('PASS: visible tofu and preserved Unicode:', ext)

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
