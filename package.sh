#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'The release archive currently supports Linux amd64 only.' >&2
  exit 1
fi
version="$(python3 -c 'import tomllib; print(tomllib.load(open("Cargo.toml", "rb"))["package"]["version"])')"
if [[ -n "${GITHUB_REF_NAME:-}" && "${GITHUB_REF_TYPE:-}" == tag && "$GITHUB_REF_NAME" != "v$version" ]]; then
  echo 'Release tag must match Cargo.toml version.' >&2
  exit 1
fi
for file in davros-preview fonts.conf licenses/DEPENDENCIES.txt licenses/Liberation.txt; do
  test -s "output/native-preview/$file" || { echo "Missing $file; run ./build.sh first" >&2; exit 1; }
done
printf '%s\n' "$version" > output/native-preview/VERSION
mkdir -p dist
archive="davros-preview-v${version}-linux-amd64.tar.gz"
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf - -C output native-preview | gzip -n > "dist/$archive"
(cd dist && sha256sum "$archive" > "$archive.sha256")
printf '%s\n' "dist/$archive"
