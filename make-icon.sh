#!/bin/zsh
# Rebuild the app icon from icon.png (any size; it's centre-cropped to a square).
#   ./make-icon.sh [path-to-image]
set -e
HERE="${0:A:h}"
SRC="${1:-$HERE/icon.png}"
[[ -f "$SRC" ]] || { echo "no image at $SRC"; exit 1; }

W=$(sips -g pixelWidth  "$SRC" | awk '/pixelWidth/{print $2}')
H=$(sips -g pixelHeight "$SRC" | awk '/pixelHeight/{print $2}')
SIDE=$(( W < H ? W : H ))
SIDE=$(( SIDE * 78 / 100 ))          # crop a bit tighter than the short edge

TMP="$(mktemp -d)"
SET="$TMP/LocalFlow.iconset"
mkdir -p "$SET"
sips -c "$SIDE" "$SIDE" "$SRC" --out "$TMP/sq.png" >/dev/null
for pair in "16:16x16" "32:16x16@2x" "32:32x32" "64:32x32@2x" \
            "128:128x128" "256:128x128@2x" "256:256x256" "512:256x256@2x" \
            "512:512x512" "1024:512x512@2x"; do
  px="${pair%%:*}"; name="${pair##*:}"
  sips -z "$px" "$px" "$TMP/sq.png" --out "$SET/icon_${name}.png" >/dev/null
done
iconutil -c icns "$SET" -o "$HERE/LocalFlow.app/Contents/Resources/AppIcon.icns"
rm -rf "$TMP"

touch "$HERE/LocalFlow.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$HERE/LocalFlow.app" 2>/dev/null || true
killall Finder 2>/dev/null || true
echo "Icon updated from: $SRC"
