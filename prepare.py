#!/usr/bin/env python3
"""Fetch checksum-pinned upstream archives and apply the reviewed local patches."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
vendor = root / 'vendor'
vendor.mkdir(exist_ok=True)
for source in json.loads((root / 'sources.json').read_text()):
    name = source['name']
    patch = root / 'patches' / (name + '.patch')
    patch_bytes = b'' if source.get('patch') is False else patch.read_bytes()
    revision = hashlib.sha256(json.dumps(source, sort_keys=True).encode() + b'\0' + patch_bytes).hexdigest()
    dest = vendor / name
    stamp = dest / '.davros-patch'
    if stamp.exists() and stamp.read_text() == revision:
        continue
    cargo_home = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
    if 'url' in source:
        cache = vendor / '.archives' / (name + '.tar.gz')
        data = cache.read_bytes() if cache.exists() else urllib.request.urlopen(source['url'], timeout=120).read()
    else:
        cached = list((cargo_home / 'registry/cache').glob('*/' + name + '.crate'))
        crate, version = name.rsplit('-', 1)
        data = cached[0].read_bytes() if cached else urllib.request.urlopen(
            f'https://static.crates.io/crates/{crate}/{name}.crate', timeout=120
        ).read()
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise RuntimeError(f'Checksum mismatch: {name}')
    if 'url' in source:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    # Stage extraction and patching before replacing a previously usable tree.
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=vendor) as temporary:
        staging = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            archive.extractall(staging, filter='data')
        unpacked = staging / source.get('archive_root', name)
        if not unpacked.is_dir():
            raise RuntimeError(f'Missing archive root: {name}')
        # One upstream package uses CRLF; the reviewed diffs use LF.
        for file in [*unpacked.rglob('*.rs'), unpacked / 'Cargo.toml']:
            file.write_text(file.read_text())
        if source.get('patch') is not False:
            subprocess.run(['patch', '-p1', '--batch', '-i', str(patch)], cwd=unpacked, check=True)
        if dest.exists():
            shutil.rmtree(dest)
        unpacked.rename(dest)
    stamp.write_text(revision)
