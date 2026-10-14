#!/usr/bin/env python3
"""Export only report assets, plus a single tar.gz for transfer."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import shutil
import tarfile
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key not in {'href', 'src'} or not value:
                continue
            url = urlsplit(value)
            if not url.scheme and not url.netloc and url.path:
                self.paths.add(unquote(url.path))


def export_report(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    archive = destination.with_name(destination.name + '.tar.gz')
    if destination.exists() or archive.exists():
        raise ValueError('Use a new destination; existing bundles are not overwritten')
    parser = Links()
    parser.feed((source / 'report.html').read_text())
    paths = parser.paths | {'report.html', 'results.json'}
    licenses = source / 'source-licenses'
    if licenses.exists():
        paths.update(str(p.relative_to(source)) for p in licenses.rglob('*') if p.is_file())
    # Validate everything before writing: no missing assets or escaping links.
    for relative in paths:
        path = (source / relative).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError(f'Invalid report asset: {relative}')
    destination.mkdir(parents=True)
    for relative in sorted(paths):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(destination, arcname=destination.name)
    return destination, archive, len(paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    directory, archive, count = export_report(args.source, args.destination)
    print(f'{directory}: {count} files')
    print(f'{archive}: {archive.stat().st_size:,} bytes')
