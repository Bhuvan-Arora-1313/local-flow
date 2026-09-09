#!/bin/zsh
# Stop LocalFlow and remove it from login items. Leaves your files & models in place.
PLIST="${HOME}/Library/LaunchAgents/com.localflow.dictation.plist"
launchctl unload "${PLIST}" 2>/dev/null || true
rm -f "${PLIST}"
pkill -f "localflow/flow.py" 2>/dev/null || true
echo "LocalFlow stopped and removed from login items."
echo "To fully remove: rm -rf ~/localflow  and  ~/miniconda3/envs/flow"
