#!/usr/bin/env python3
"""Preparation must verify archives and preserve the last usable patched tree."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

prepare = Path(__file__).resolve().parents[1] / 'prepare.py'
with tempfile.TemporaryDirectory(prefix='davros-prepare-test-') as temporary:
    root = Path(temporary)
    cache = root / 'vendor/.archives'
    cache.mkdir(parents=True)
    patches = root / 'patches'
    patches.mkdir()
    archive = cache / 'example-revision.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in [('Cargo.toml', b'[workspace]\n'), ('src/lib.rs', b'original\n')]:
            info = tarfile.TarInfo('archive-root/' + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (root / 'sources.json').write_text(json.dumps([dict(
        name='example-revision', url='https://invalid.example/not-fetched',
        archive_root='archive-root', sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )]))
    patch = patches / 'example-revision.patch'
    patch.write_text('--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1 +1 @@\n-original\n+patched\n')
    subprocess.run([sys.executable, prepare, root], check=True, capture_output=True)
    dest = root / 'vendor/example-revision'
    stamp = (dest / '.davros-patch').read_text()
    assert (dest / 'src/lib.rs').read_text() == 'patched\n'
    # A failed upgrade must not remove the previously working source or stamp.
    patch.write_text('--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1 +1 @@\n-missing\n+bad\n')
    failed = subprocess.run([sys.executable, prepare, root], capture_output=True)
    assert failed.returncode
    assert (dest / 'src/lib.rs').read_text() == 'patched\n'
    assert (dest / '.davros-patch').read_text() == stamp
    assert not list((root / 'vendor').glob('.prepare-*'))
    archive.write_bytes(b'corrupt archive')
    failed = subprocess.run([sys.executable, prepare, root], capture_output=True)
    assert failed.returncode and b'Checksum mismatch' in failed.stderr
    assert (dest / 'src/lib.rs').read_text() == 'patched\n'
print('PASS: preparation verifies archives and preserves usable source after failures')
