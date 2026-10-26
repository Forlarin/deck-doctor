#!/usr/bin/env bash
# Build out/deck-doctor.zip in the layout Decky's "Install plugin from ZIP" expects:
# one top-level folder holding plugin.json, main.py, dist/ and py_modules/.
set -euo pipefail
cd "$(dirname "$0")/.."

npx pnpm@9 build >/dev/null
python3 -m unittest discover -s tests >/dev/null 2>&1 || { echo "Tests failed, not packaging." >&2; exit 1; }

STAGE=$(mktemp -d)
PKG="$STAGE/deck-doctor"
mkdir -p "$PKG/dist" "$PKG/py_modules/deck_doctor"
cp plugin.json main.py package.json LICENSE README.md "$PKG/"
cp dist/index.js "$PKG/dist/"
cp py_modules/deck_doctor/*.py "$PKG/py_modules/deck_doctor/"

mkdir -p out
rm -f out/deck-doctor.zip
(cd "$STAGE" && zip -qrX "$OLDPWD/out/deck-doctor.zip" deck-doctor)
rm -r "$STAGE"
unzip -l out/deck-doctor.zip
