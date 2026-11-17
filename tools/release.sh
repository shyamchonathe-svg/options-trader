#!/bin/bash
# Deploy a tag/branch from the git clone on the VM (replaces the chunk-paste bundle).
# Usage (on the VM):  cd ~/trader/repo && bash tools/release.sh v1.0.1     # or a branch name
# Steps: fetch -> export that ref to ~/trader/releases/<version> -> run tests -> switch ~/trader/current -> restart.
# Roll back:  ln -sfn ~/trader/releases/<old> ~/trader/current && sudo systemctl restart trader.service
set -e
REF="${1:?usage: release.sh <tag-or-branch>}"
cd "$(dirname "$0")/.."
git fetch --tags --prune origin
if git rev-parse -q --verify "origin/$REF" >/dev/null; then TARGET="origin/$REF"; else TARGET="$REF"; fi
SHA=$(git rev-parse --short "$TARGET")
VER=$(git describe --tags --exact-match "$TARGET" 2>/dev/null || echo "$(echo "$REF" | tr / -)-$SHA")
DEST="$HOME/trader/releases/$VER"
mkdir -p "$DEST"
git archive "$TARGET" | tar -x -C "$DEST"
printf 'version=%s\ncommit=%s\nbranch=%s\nbuilt=%s\nworking_tree_dirty=False\n' \
  "$VER" "$(git rev-parse "$TARGET")" "$REF" "$(date '+%Y-%m-%d %H:%M:%S')" > "$DEST/VERSION"
( cd "$DEST" && "$HOME/trader/venv/bin/python" -m unittest discover -s tests -t . 2>&1 | tail -4 )
read -r -p "Tests above OK? Switch to $VER and restart? [y/N] " A
[ "$A" = "y" ] || { echo "not switched (release unpacked at $DEST)"; exit 1; }
ln -sfn "$DEST" "$HOME/trader/current"
sudo systemctl restart trader.service
echo "now running $VER"
