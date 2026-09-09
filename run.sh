#!/bin/zsh
# Run LocalFlow in the foreground (logs to the terminal). Ctrl-C to stop.
# Use this the first few times so macOS shows the permission prompts and you
# can see what the model is doing. For always-on use, run ./install.sh instead.
HERE="${0:A:h}"
cd "$HERE" || exit 1

PYTHON="$(cat "$HERE/.python-path" 2>/dev/null)"
[[ -x "$PYTHON" ]] || PYTHON="${HOME}/miniconda3/envs/flow/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

if [[ ! -x "$PYTHON" && "$PYTHON" != "python3" ]]; then
  echo "No Python env found. Run ./setup.sh first."; exit 1
fi
exec "$PYTHON" flow.py
