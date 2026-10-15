#!/usr/bin/env python3
"""Reproduce the DOCX run-wrapper stack overflow without private documents.

Diagnostic only, not part of test.sh. Exits nonzero if conversion crashes, times
out, or unexpectedly succeeds; a future bounded rejection should make it pass.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parent.parent
bundle = root / 'output/native-preview'
env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
           FONTCONFIG_FILE=str(bundle / 'fonts.conf'))
with tempfile.TemporaryDirectory(prefix='davros-docx-depth-') as temporary:
    work = Path(temporary)
    scratch = work / 'scratch'
    scratch.mkdir()
    source = work / 'nested.docx'
    with zipfile.ZipFile(root / 'tests/fixtures/basic.docx') as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    run = b'<w:r><w:t>Selectable preview text</w:t></w:r>'
    entries['word/document.xml'] = entries['word/document.xml'].replace(
        run, b'<w:smartTag>' * 10000 + run + b'</w:smartTag>' * 10000)
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    print(f'Input: {source.stat().st_size} compressed bytes, 10000 nested run wrappers', flush=True)
    try:
        result = subprocess.run([bundle / 'davros-preview', source, scratch / 'preview.pdf'],
                                env=env, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        raise SystemExit('FAIL: converter exceeded five-second diagnostic timeout')
    print(result.stderr, end='')
    if result.returncode < 0:
        raise SystemExit(f'FAIL: converter terminated by signal {-result.returncode}')
    if result.returncode == 0:
        raise SystemExit('REVIEW: document succeeded; verify a structural bound before updating this probe')
    print('PASS: converter rejected the input without a signal')
