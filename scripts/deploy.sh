#!/usr/bin/env bash
# Build Deck Doctor and copy it to a Steam Deck over SSH, then verify every file arrived.
#
#   scripts/deploy.sh [deck@host]
#
# plugin.json is owned by root once Decky has loaded the plugin, so it is only
# checked here; if it differs, the script prints the sudo command to update it.
set -euo pipefail

HOST="${1:-deck@steamdeck.local}"
DEST="homebrew/plugins/deck-doctor"
cd "$(dirname "$0")/.."

npx pnpm@9 build >/dev/null
FILES=(dist/index.js main.py package.json py_modules/deck_doctor/*.py)

ssh "$HOST" "mkdir -p $DEST/dist $DEST/py_modules/deck_doctor"
for f in "${FILES[@]}"; do
  scp -q "$f" "$HOST:$DEST/$f"
done

local_sums=$(shasum "${FILES[@]}" plugin.json | awk '{print $1"  "$2}')
remote_sums=$(ssh "$HOST" "cd $DEST && sha1sum ${FILES[*]} plugin.json")
if ! diff <(echo "$local_sums") <(echo "$remote_sums") >/tmp/deck-doctor-deploy.diff; then
  if grep -q plugin.json /tmp/deck-doctor-deploy.diff && [ "$(grep -c '^[<>]' /tmp/deck-doctor-deploy.diff)" -eq 2 ]; then
    echo "plugin.json differs (root-owned). Update it with:"
    echo "  scp plugin.json $HOST:/tmp/ && ssh -t $HOST 'sudo cp /tmp/plugin.json ~/$DEST/ && sudo systemctl restart plugin_loader'"
  else
    echo "Deploy FAILED, these files don't match:" >&2
    cat /tmp/deck-doctor-deploy.diff >&2
    exit 1
  fi
fi
echo "Deployed ${#FILES[@]} files, all checksums match."
