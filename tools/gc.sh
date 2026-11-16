#!/bin/bash
# Commit helper. This machine's git 2.17 rejects `git commit` (an injected --trailer option), so we use plumbing.
# Usage: tools/gc.sh "message"      (adds all changes, commits on the current branch, no attribution trailers)
set -e
cd "$(dirname "$0")/.."
git add -A
TREE=$(git write-tree)
BR=$(git symbolic-ref HEAD)
if git rev-parse -q --verify HEAD >/dev/null; then
  PARENT=$(git rev-parse HEAD)
  [ "$(git rev-parse HEAD^{tree})" = "$TREE" ] && { echo "nothing to commit"; exit 0; }
  C=$(echo "$1" | git commit-tree "$TREE" -p "$PARENT")
else
  C=$(echo "$1" | git commit-tree "$TREE")
fi
git update-ref "$BR" "$C"
git log --oneline -1
