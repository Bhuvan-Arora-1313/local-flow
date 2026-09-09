#!/bin/zsh
# Stop LocalFlow and remove it from login items. Leaves your files & models in place.
HERE="${0:A:h}"
PLIST="${HOME}/Library/LaunchAgents/com.localflow.dictation.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "${DOMAIN}/com.localflow.dictation" 2>/dev/null || true
launchctl unload "${PLIST}" 2>/dev/null || true
rm -f "${PLIST}"
pkill -f "${HERE}/flow.py" 2>/dev/null || true
pkill -f "localflow/flow.py" 2>/dev/null || true

echo "LocalFlow stopped and removed from login items."
echo "(You can still start it manually with ./run.sh or 'localflow start'.)"
echo "To remove completely:  rm -rf '${HERE}'  and the Python env it made."
