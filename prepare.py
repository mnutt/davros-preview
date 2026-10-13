#!/usr/bin/env python3
"""Fetch checksum-pinned upstream crates and apply the reviewed local patches."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
vendor = root / 'vendor'
vendor.mkdir(exist_ok=True)
for source in json.loads((root / 'sources.json').read_text()):
    name = source['name']
    patch = root / 'patches' / (name + '.patch')
    revision = hashlib.sha256(patch.read_bytes()).hexdigest()
    dest = vendor / name
    stamp = dest / '.davros-patch'
    if stamp.exists() and stamp.read_text() == revision:
        continue
    cargo_home = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
    cached = list((cargo_home / 'registry/cache').glob('*/' + name + '.crate'))
    crate, version = name.rsplit('-', 1)
    data = cached[0].read_bytes() if cached else urllib.request.urlopen(
        f'https://static.crates.io/crates/{crate}/{name}.crate', timeout=120
    ).read()
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise RuntimeError(f'Checksum mismatch: {name}')
    if dest.exists():
        shutil.rmtree(dest)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        archive.extractall(vendor, filter='data')
    # One upstream package uses CRLF; the reviewed diffs use LF.
    for file in [*dest.rglob('*.rs'), dest / 'Cargo.toml']:
        file.write_text(file.read_text())
    subprocess.run(['patch', '-p1', '--batch', '-i', str(patch)], cwd=dest, check=True)
    stamp.write_text(revision)
