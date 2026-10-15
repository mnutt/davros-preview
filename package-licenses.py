#!/usr/bin/env python3
"""Copy dependency notices and the MPL-covered hatch source into the bundle."""
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
    odf_workspace = root / 'vendor/libreoffice-rs-16532b3'
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
# lo_impress ships third-party preset geometry and an MPL-licensed hatch table.
# Their notices are nested under data/, outside Cargo's usual license locations.
impress = odf_workspace / 'crates/lo_impress'
for name in ['APACHE-POI-LICENSE', 'APACHE-POI-NOTICE', 'LIBREOFFICE-MPL-2.0']:
    file = impress / 'data' / name
    licenses.setdefault(file.read_text().strip(), []).append(f'lo_impress/data/{name}')
for name in ['hatch-source.json', 'preset-shapes-source.json']:
    shutil.copyfile(impress / 'data' / name, out / ('lo_impress-' + name))
# Include the complete small MPL-covered source alongside its license.
shutil.copyfile(impress / 'src/pptx_pattern.rs', out / 'lo_impress-pptx_pattern.rs')
(out / 'DEPENDENCIES.txt').write_text('\n'.join(notices) + '\n')
(out / 'LICENSES.txt').write_text('\n\n'.join(
    '\n'.join(names) + '\n\n' + content for content, names in licenses.items()
) + '\n')
font_license = next((p for p in [
    Path('/usr/share/doc/fonts-liberation/copyright'),
    Path('/usr/share/licenses/ttf-liberation/LICENSE'),
] if p.exists()), None)
if font_license is None:
    raise SystemExit('Missing Liberation font license')
shutil.copyfile(font_license, out / 'Liberation.txt')

# The fallback font retains its embedded copyright and OFL metadata. Include
# upstream OFL text as well; distro copyright files carry version-specific notices.
shutil.copyfile(root / 'licenses/NotoSans-OFL.txt', out / 'NotoSans-OFL.txt')
noto_copyright = Path('/usr/share/doc/fonts-noto-core/copyright')
if noto_copyright.is_file():
    shutil.copyfile(noto_copyright, out / 'NotoSans-distro-copyright.txt')
