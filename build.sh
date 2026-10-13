#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 prepare.py
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/target}"
cargo build --release --locked --bins -j "${CARGO_BUILD_JOBS:-1}"
mkdir -p output/native-preview/fonts
cp "$CARGO_TARGET_DIR/release/davros-preview" output/native-preview/
python3 - <<'PY'
from pathlib import Path
import shutil
# Remove obsolete entry points when rebuilding an existing output directory.
for name in ['davros-docx', 'davros-office']:
    (Path('output/native-preview') / name).unlink(missing_ok=True)
for family in ['Sans', 'Serif', 'Mono']:
    for face in ['Regular', 'Bold', 'Italic', 'BoldItalic']:
        name = f'Liberation{family}-{face}.ttf'
        matches = list(Path('/usr/share/fonts').rglob(name))
        if not matches:
            raise SystemExit(f'Missing {name}; install fonts-liberation')
        shutil.copyfile(matches[0], Path('output/native-preview/fonts') / name)
PY
cp fonts.conf THIRD_PARTY_NOTICES LICENSE output/native-preview/
python3 package-licenses.py
