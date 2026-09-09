#!/bin/zsh
# Run LocalFlow in the foreground (logs to the terminal). Ctrl-C to stop.
# Use this the first few times so macOS shows the permission prompts and you
# can see what the model is doing. For always-on use, run ./install.sh instead.
HERE="${0:A:h}"
cd "$HERE" || exit 1

PYTHON="$(cat "$HERE/.python-path" 2>/dev/null)"
[[ -x "$PYTHON" ]] || PYTHON="${HOME}/miniconda3/envs/flow/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

if [[ ! -x "$PYTHON" ]]; then
  echo "No Python env found. Run ./setup.sh first."; exit 1
fi

# skip the network check once the model is cached
if ls "${HOME}/.cache/huggingface/hub/models--mlx-community--parakeet-tdt-0.6b-v3/snapshots/"*/config.json >/dev/null 2>&1; then
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
fi

exec "$PYTHON" "$HERE/flow.py"
