#!/bin/zsh
# LocalFlow one-shot setup. Creates an isolated Python 3.12 env, installs deps,
# and writes .python-path so the launch scripts know which interpreter to use.
set -e
HERE="${0:A:h}"
cd "$HERE"

echo "LocalFlow setup"
echo "==============="

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "!! This needs an Apple Silicon Mac (M1/M2/M3/M4). Aborting."
  exit 1
fi

# --- find conda, if any (it may not be on PATH in a non-interactive shell) ---
CONDA=""
if command -v conda >/dev/null 2>&1; then
  CONDA="conda"
else
  for c in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
           "$HOME/miniforge3/bin/conda" "/opt/homebrew/bin/conda"; do
    [[ -x "$c" ]] && CONDA="$c" && break
  done
fi

PYBIN=""
if [[ -n "$CONDA" ]]; then
  echo "• conda found -> env 'localflow-env' (Python 3.12)"
  if "$CONDA" env list | grep -qE '/localflow-env$|^localflow-env '; then
    echo "  (env already exists, reusing)"
  else
    "$CONDA" create -y -n localflow-env python=3.12 >/dev/null
  fi
  PYBIN="$("$CONDA" run -n localflow-env python -c 'import sys; print(sys.executable)')"
else
  echo "• no conda -> using a python3 venv (.venv)"
  PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  case "$PYV" in
    3.10|3.11|3.12) : ;;
    *) echo "  WARNING: python3 is $PYV. 3.10-3.12 is strongly recommended"
       echo "  (mlx / torch may have no wheels for $PYV). Install Miniconda and"
       echo "  re-run this script if pip install fails below." ;;
  esac
  python3 -m venv .venv
  PYBIN="$HERE/.venv/bin/python"
fi

echo "• installing dependencies (a few minutes; ~250 MB download)…"
"$PYBIN" -m pip install --quiet --upgrade pip
"$PYBIN" -m pip install --quiet -r requirements.txt

echo "$PYBIN" > "$HERE/.python-path"
chmod +x "$HERE"/*.sh "$HERE/localflow" 2>/dev/null || true

echo "• building the app launcher…"
"$HERE/build-launcher.sh" || echo "  (build failed — you can still use ./run.sh)"

echo "• downloading the speech model (~0.6 GB, one time)…"
"$PYBIN" - <<'PY'
from parakeet_mlx import from_pretrained
from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
print("  model ready.")
PY

cat <<EOF

Done.  Interpreter: $PYBIN

Next:
  1. (optional) jargon cleanup pass:  install Ollama from https://ollama.com
       then:  ollama pull qwen3:8b
  2. Start it:   ./run.sh
  3. Grant permissions when macOS asks (or add the launching app -- Terminal, or
     LocalFlow -- in System Settings > Privacy & Security):
       Microphone · Input Monitoring · Accessibility
  4. Hold Right Option, speak, release.

Always-on / background use:  ./install.sh
EOF
