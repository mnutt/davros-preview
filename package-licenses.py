#!/usr/bin/env python3
"""Copy dependency notices next to the binaries (no compiler/source in the package)."""
import os
from pathlib import Path
import shutil
import tomllib

root = Path(__file__).resolve().parent
out = root / 'output/native-preview/licenses'
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True, exist_ok=True)
cargo = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
notices = []
licenses = {}
for package in tomllib.loads((root / 'Cargo.lock').read_text())['package']:
    name = f"{package['name']}-{package['version']}"
    odf_workspace = root / 'vendor/libreoffice-rs-291b94a'
    sources = [root / 'vendor' / name,
               odf_workspace / 'crates' / package['name'],
               *(cargo / 'registry/src').glob('*/' + name)]
    source = next((p for p in sources if p.exists()), None)
    if source is None:
        continue  # Cargo.lock also includes dependencies for other platforms.
    manifest = tomllib.loads((source / 'Cargo.toml').read_text())['package']
    license_dirs = [source]
    if source.parent == odf_workspace / 'crates':
        inherited = tomllib.loads((odf_workspace / 'Cargo.toml').read_text())['workspace']['package']
        for key in ('license', 'repository'):
            if isinstance(manifest.get(key), dict) and manifest[key].get('workspace'):
                manifest[key] = inherited[key]
        license_dirs.append(odf_workspace)
    notices.append(f"{name}: {manifest.get('license', 'see license file')} {manifest.get('repository', '')}")
    for file in (file for directory in license_dirs for file in directory.iterdir()):
        if file.is_file() and file.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
            content = file.read_text(errors='replace').strip()
            licenses.setdefault(content, []).append(f'{name}/{file.name}')
(out / 'DEPENDENCIES.txt').write_text('\n'.join(notices) + '\n')
(out / 'LICENSES.txt').write_text('\n\n'.join(
    '\n'.join(names) + '\n\n' + content for content, names in licenses.items()
) + '\n')
# office2pdf declares Apache-2.0 but omits its license file from the published crate.
shutil.copyfile(root / 'vendor/docxide-pdf-0.17.1/LICENSE', out / 'Apache-2.0.txt')
font_license = next((p for p in [
    Path('/usr/share/doc/fonts-liberation/copyright'),
    Path('/usr/share/licenses/ttf-liberation/LICENSE'),
] if p.exists()), None)
if font_license is None:
    raise SystemExit('Missing Liberation font license')
shutil.copyfile(font_license, out / 'Liberation.txt')
