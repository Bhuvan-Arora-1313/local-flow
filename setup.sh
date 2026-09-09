#!/bin/zsh
# LocalFlow one-shot setup. Creates an isolated Python 3.12 env, installs deps,
# and writes .python-path so the launch scripts know which interpreter to use.
set -e
HERE="${0:A:h}"
cd "$HERE"

echo "LocalFlow setup"
echo "==============="

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "warning: this is built for Apple Silicon (M1/M2/M3/M4). Intel Macs will be slow or unsupported."
fi

PYBIN=""
if command -v conda >/dev/null 2>&1; then
  echo "• using conda -> env 'localflow' (python 3.12)"
  conda create -y -n localflow python=3.12 >/dev/null
  PYBIN="$(conda run -n localflow python -c 'import sys; print(sys.executable)')"
else
  echo "• conda not found -> using python3 venv (.venv)"
  PYV="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
  case "$PYV" in
    3.10|3.11|3.12) : ;;
    *) echo "  note: python3 is $PYV; 3.10–3.12 works best (mlx/torch wheels). Continuing anyway." ;;
  esac
  python3 -m venv .venv
  PYBIN="$HERE/.venv/bin/python"
fi

echo "• installing dependencies (a few minutes; downloads ~200 MB)…"
"$PYBIN" -m pip install --quiet --upgrade pip
"$PYBIN" -m pip install --quiet -r requirements.txt

echo "$PYBIN" > "$HERE/.python-path"
chmod +x "$HERE/run.sh" "$HERE/install.sh" "$HERE/uninstall.sh" "$HERE/localflow" \
         "$HERE/LocalFlow.app/Contents/MacOS/LocalFlow" 2>/dev/null || true

echo "• downloading the speech model (~0.6 GB, one time)…"
"$PYBIN" - <<'PY'
from parakeet_mlx import from_pretrained
from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
print("  model ready.")
PY

cat <<EOF

Done.

Next:
  1. (optional, for jargon cleanup)  install Ollama from https://ollama.com
       then:  ollama pull qwen3:8b
  2. Start it:            ./run.sh
  3. Grant permissions when macOS asks (or add "LocalFlow" / your terminal in
     System Settings > Privacy & Security):
       Microphone · Input Monitoring · Accessibility
  4. Hold Right Option, speak, release.

Background use:  ./install.sh   (adds a 'localflow' command + start at login)
EOF
