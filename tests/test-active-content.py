#!/usr/bin/env python3
"""Synthetic active-content regressions; --trace also checks Linux syscalls.

Opaque macro/object parts are deliberately inert, not a valid VBA exploit corpus.
This tests representative dispatch paths, not absence of memory-safety bugs.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests/corpus/odf'))
from native_fixtures import build, package


def read_zip(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', action='store_true', help='requires strace and ptrace permission; disables Landlock and dumpability hardening for observation')
    args = parser.parse_args()
    bundle = ROOT / 'output/native-preview'
    env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
               FONTCONFIG_FILE=str(bundle / 'fonts.conf'))
    with tempfile.TemporaryDirectory(prefix='davros-active-content-') as tmp:
        root = Path(tmp)
        canary = root / 'external-secret.txt'
        canary.write_text('DAVROS_EXTERNAL_SECRET_74891')
        marker = root / 'script-ran'
        external = 'http://127.0.0.1:9/davros-security-no-fetch'
        rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        office_rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        sources = list(sorted((ROOT / 'tests/fixtures').iterdir())) + build(root / 'odf')

        entries = read_zip(ROOT / 'tests/fixtures/basic.docx')
        xml = entries['word/document.xml'].decode().replace('<w:document ', f'<w:document xmlns:r="{office_rel}" ')
        additions = (
            f'<w:p><w:fldSimple w:instr={quoteattr("DDEAUTO /bin/sh "+str(marker))}>'
            '<w:r><w:t>Cached DDE result</w:t></w:r></w:fldSimple></w:p>'
            f'<w:p><w:fldSimple w:instr={quoteattr("INCLUDETEXT "+canary.as_uri())}>'
            '<w:r><w:t>Cached include result</w:t></w:r></w:fldSimple></w:p>'
            '<w:p><w:hyperlink r:id="link"><w:r><w:t>Untrusted link</w:t></w:r></w:hyperlink></w:p>'
            '<w:altChunk r:id="external"/>'
        )
        entries['word/document.xml'] = xml.replace('<w:sectPr>', additions+'<w:sectPr>').encode()
        entries['word/_rels/document.xml.rels'] = (
            f'<Relationships xmlns="{rel_ns}">'
            f'<Relationship Id="link" Type="{office_rel}/hyperlink" Target="javascript:alert(1)" TargetMode="External"/>'
            f'<Relationship Id="external" Type="{office_rel}/aFChunk" Target="{external}" TargetMode="External"/>'
            f'<Relationship Id="macro" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/>'
            '</Relationships>').encode()
        entries['word/vbaProject.bin'] = b'INERT VBA PART SENTINEL'
        entries['word/embeddings/oleObject1.bin'] = b'INERT OLE PART SENTINEL'
        source = root / 'active.docx'
        write_zip(source, entries)
        sources.append(source)

        entries = read_zip(ROOT / 'tests/fixtures/basic.xlsx')
        xml = entries['xl/worksheets/sheet1.xml'].decode()
        formula = escape(f'WEBSERVICE("{external}")')
        xml = xml.replace('<c r="B1" s="1"><v>0.125</v></c>',
                          f'<c r="B1" s="1"><f>{formula}</f><v>0.125</v></c>')
        xml = xml.replace('<c r="C1" s="2"><v>12.5</v></c>',
                          '<c r="C1" s="2"><f>EXEC("ignored")</f><v>12.5</v></c>')
        entries['xl/worksheets/sheet1.xml'] = xml.encode()
        entries['xl/vbaProject.bin'] = b'INERT VBA PART SENTINEL'
        source = root / 'active.xlsx'
        write_zip(source, entries)
        sources.append(source)

        entries = read_zip(ROOT / 'tests/fixtures/basic.pptx')
        xml = entries['ppt/slides/slide1.xml'].decode()
        pic = ('<p:pic><p:nvPicPr><p:cNvPr id="3" name="External image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
               '<p:blipFill><a:blip r:link="external"/></p:blipFill>'
               '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm></p:spPr></p:pic>')
        entries['ppt/slides/slide1.xml'] = xml.replace('</p:spTree>',pic+'</p:spTree>').encode()
        entries['ppt/slides/_rels/slide1.xml.rels'] = (
            f'<Relationships xmlns="{rel_ns}"><Relationship Id="external" Type="{office_rel}/image" '
            f'Target="{external}" TargetMode="External"/></Relationships>').encode()
        entries['ppt/vbaProject.bin'] = b'INERT VBA PART SENTINEL'
        source = root / 'active.pptx'
        write_zip(source, entries)
        sources.append(source)

        source = root / 'active.odt'
        package(source, 'text', '<office:text><text:p>Active content control</text:p>'
                f'<text:section text:name="External"><text:section-source xlink:href="{canary.as_uri()}"/>'
                '<text:p>Cached section</text:p></text:section>'
                '<text:p><text:a xlink:href="javascript:alert(1)">Untrusted link</text:a></text:p></office:text>')
        entries = read_zip(source)
        script = f'<office:scripts><office:script script:language="ooo:Basic" xmlns:script="urn:oasis:names:tc:opendocument:xmlns:script:1.0">Sub Main\nShell("/usr/bin/touch {marker}")\nEnd Sub</office:script></office:scripts>'
        entries['content.xml'] = entries['content.xml'].replace(b'<office:body>',script.encode()+b'<office:body>')
        write_zip(source, entries)
        sources.append(source)

        source = root / 'active-svg.odp'
        package(source, 'presentation', '<office:presentation><draw:page draw:name="Test">'
                '<draw:frame svg:x="1in" svg:y="1in" svg:width="2in" svg:height="2in">'
                '<draw:image xlink:href="Pictures/active.svg"/></draw:frame></draw:page></office:presentation>')
        entries = read_zip(source)
        entries['Pictures/active.svg'] = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<script>throw new Error("DAVROS_SCRIPT_SENTINEL")</script>'
            f'<image href="{canary.as_uri()}" width="20" height="20"/>'
            f'<image href="{external}" width="20" height="20"/>'
            '<rect width="100" height="100" fill="red"/></svg>').encode()
        write_zip(source, entries)
        sources.append(source)

        # DTD/entity inputs may be rejected, but must never resolve external data.
        rejection_allowed = set()
        for ext, original, part, root_name in [
            ('docx', ROOT / 'tests/fixtures/basic.docx', 'word/document.xml', 'w:document'),
            ('odt', root / 'active.odt', 'content.xml', 'office:document-content'),
        ]:
            entries = read_zip(original)
            dtd = f'<!DOCTYPE {root_name} [<!ENTITY external SYSTEM "{canary.as_uri()}">]>'
            entries[part] = dtd.encode() + entries[part].replace(
                b'Selectable preview text' if ext == 'docx' else b'Active content control',
                b'&external;')
            source = root / ('external-entity.' + ext)
            write_zip(source, entries)
            sources.append(source)
            rejection_allowed.add(source.name)

        for index, source in enumerate(sources):
            scratch = root / f'job-{index}'
            scratch.mkdir()
            pdf = scratch / 'preview.pdf'
            command = [str(bundle / 'davros-preview'), str(source), str(pdf)]
            trace = root / f'trace-{index}'
            if args.trace:
                # Deny the ABI query to exercise parser behavior without Landlock.
                # Keep the process dumpable so strace can decode syscall arguments.
                command = ['strace', '-f', '-qq', '-s', '2048',
                           '-e', 'inject=landlock_create_ruleset:error=ENOSYS:when=1',
                           '-e', 'inject=prctl:retval=0:when=1',
                           '-e', 'trace=%process,%network,%file,prctl,landlock_create_ruleset',
                           '-o', str(trace), *command]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
            assert result.returncode >= 0, (source.name, 'signal/crash', result.stderr)
            assert result.returncode == 0 or source.name in rejection_allowed, (source.name, result.stderr)
            data = pdf.read_bytes() if result.returncode == 0 else b''
            assert data.startswith(b'%PDF-') or source.name in rejection_allowed, source.name
            assert not marker.exists(), source.name
            assert not re.search(rb'/(JavaScript|JS|Launch|OpenAction|EmbeddedFiles)\b', data), source.name
            text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True) if result.returncode == 0 else ''
            assert canary.read_text() not in text, source.name
            if args.trace:
                log = trace.read_text()
                assert 'Landlock filesystem isolation unavailable' in result.stderr
                assert 'PR_SET_DUMPABLE' in log and '(INJECTED)' in log, log
                assert 'process_dumping_disabled' in result.stderr, result.stderr
                execs = re.findall(r'\bexecve(?:at)?\(', log)
                assert len(execs) == 1, (source.name, 'unexpected execution', log)
                assert not re.search(r'\b(socket|socketpair|connect|sendto|sendmsg)\(', log), (source.name, 'network syscall', log)
                assert str(canary) not in log, (source.name, 'external file access', log)
                for line in log.splitlines():
                    if re.search(r'\b(clone3?|fork|vfork)\(', line):
                        assert 'CLONE_THREAD' in line, (source.name, 'non-thread process creation', line)
            if b'javascript:' in data:
                print('REVIEW: unfiltered javascript: URI annotation survives in', source.name)
            print('PASS:', source.name)
        print(f'PASS: {len(sources)} conversions; syscall tracing={args.trace}')


if __name__ == '__main__':
    main()
