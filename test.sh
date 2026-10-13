#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/target}"
cargo test --locked -p office_oxide --lib -j "${CARGO_BUILD_JOBS:-1}"
cargo build --release --locked --example sandbox-check -j "${CARGO_BUILD_JOBS:-1}"
python3 test-sandbox.py "$CARGO_TARGET_DIR/release/examples/sandbox-check"
python3 tests/test-conversion.py
python3 tests/corpus/test_runner.py
