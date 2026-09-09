#!/bin/bash
# One-line installer for LocalFlow.
#   curl -fsSL https://raw.githubusercontent.com/Bhuvan-Arora-1313/local-flow/main/bootstrap.sh | bash
#
# Clones the repo to ~/localflow (or $1) and runs ./setup.sh.
set -e
REPO="https://github.com/Bhuvan-Arora-1313/local-flow.git"
DIR="${1:-$HOME/localflow}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "LocalFlow needs an Apple Silicon Mac (M1 or newer)."; exit 1
fi

if [ -d "$DIR/.git" ]; then
  echo "• updating existing checkout in $DIR"
  git -C "$DIR" pull --ff-only || echo "  (skipped update — 'cd $DIR && git status' to check)"
else
  echo "• cloning into $DIR"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
exec ./setup.sh
