#!/bin/zsh
# Compile LocalFlow.app/Contents/MacOS/LocalFlow — a native binary that embeds
# the project's Python. Called by setup.sh and install.sh.
set -e
HERE="${0:A:h}"
PY="$(cat "$HERE/.python-path" 2>/dev/null)"
[[ -x "$PY" ]] || { echo "build-launcher: no .python-path"; exit 1; }

PREFIX="$("$PY" -c 'import sys; print(sys.prefix)')"
VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
INC="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
LIBDIR="$PREFIX/lib"
[[ -f "$LIBDIR/libpython${VER}.dylib" ]] || LIBDIR="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"

OUT="$HERE/LocalFlow.app/Contents/MacOS/LocalFlow"
mkdir -p "$HERE/LocalFlow.app/Contents/MacOS" "$HERE/LocalFlow.app/Contents/Resources"

clang -O2 -DPYLIB_PREFIX="\"${PREFIX}\"" "$HERE/launcher.c" \
  -I"$INC" -L"$LIBDIR" -lpython${VER} -Wl,-rpath,"$LIBDIR" \
  -framework CoreFoundation -o "$OUT"
chmod +x "$OUT"
print -r -- "$HERE" > "$HERE/LocalFlow.app/Contents/Resources/localflow_home"

# Ad-hoc sign so macOS keeps the Privacy permissions attached to a stable identity
# and shows the permission prompts properly.
codesign --force --deep -s - "$HERE/LocalFlow.app" 2>/dev/null || true

echo "build-launcher: built + signed $OUT  (python ${VER}, prefix ${PREFIX})"
