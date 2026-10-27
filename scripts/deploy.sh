#!/usr/bin/env bash
# Build Deck Doctor, stage it on a Steam Deck over SSH, and verify every file arrived.
#
#   scripts/deploy.sh [deck@host]
#
# Decky makes a root plugin's folder root-owned, so the files are staged in
# ~/deck-doctor-stage and the script prints the one sudo command that installs
# them and restarts Decky (run it in a terminal so you can type the password).
set -euo pipefail

HOST="${1:-deck@steamdeck.local}"
STAGE="deck-doctor-stage"
cd "$(dirname "$0")/.."

npx pnpm@9 build >/dev/null
FILES=(dist/index.js main.py package.json plugin.json py_modules/deck_doctor/*.py docs/fixes/*.md)

ssh "$HOST" "rm -rf $STAGE && mkdir -p $STAGE/dist $STAGE/py_modules/deck_doctor $STAGE/docs/fixes"
for f in "${FILES[@]}"; do
  scp -q "$f" "$HOST:$STAGE/$f"
done

if ! diff <(shasum "${FILES[@]}" | awk '{print $1"  "$2}') <(ssh "$HOST" "cd $STAGE && sha1sum ${FILES[*]}") >&2; then
  echo "Staging FAILED: the files above don't match." >&2
  exit 1
fi
echo "Staged ${#FILES[@]} files on $HOST, all checksums match. To install and restart Decky:"
echo "  ssh -t $HOST \"sudo cp -rT ~/$STAGE ~/homebrew/plugins/deck-doctor && rm -rf ~/$STAGE && sudo systemctl restart plugin_loader && echo INSTALLED\""
