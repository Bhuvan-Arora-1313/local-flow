#!/bin/zsh
# Install LocalFlow as an always-on menu-bar app that starts at login.
set -e
HERE="${0:A:h}"

chmod +x "${HERE}"/*.sh "${HERE}/localflow" \
         "${HERE}/LocalFlow.app/Contents/MacOS/LocalFlow" 2>/dev/null || true

[[ -f "${HERE}/.python-path" ]] || { echo "Run ./setup.sh first (no .python-path)."; exit 1; }

# Make `localflow` runnable from anywhere: symlink into a PATH dir, else add an alias.
if LINKDIR=$(for d in "$HOME/bin" "$HOME/.local/bin" /usr/local/bin; do
      [[ -d "$d" && -w "$d" ]] && echo "$d" && break; done); [[ -n "$LINKDIR" ]]; then
  ln -sf "${HERE}/localflow" "${LINKDIR}/localflow"
  echo "Installed command: ${LINKDIR}/localflow"
else
  RC="${HOME}/.zshrc"
  grep -q "alias localflow=" "$RC" 2>/dev/null || \
    echo "alias localflow='${HERE}/localflow'" >> "$RC"
  echo "Added 'localflow' alias to ${RC} (open a new terminal to use it)."
fi

PLIST="${HOME}/Library/LaunchAgents/com.localflow.dictation.plist"
DOMAIN="gui/$(id -u)"
mkdir -p "${HOME}/Library/LaunchAgents"
sed -e "s#__LOCALFLOW_HOME__#${HERE}#g" \
    "${HERE}/com.localflow.dictation.plist" > "${PLIST}"

launchctl bootout "${DOMAIN}/com.localflow.dictation" 2>/dev/null || true
launchctl unload "${PLIST}" 2>/dev/null || true
pkill -f "${HERE}/flow.py" 2>/dev/null || true
sleep 1
launchctl bootstrap "${DOMAIN}" "${PLIST}"
launchctl enable "${DOMAIN}/com.localflow.dictation" 2>/dev/null || true

# Put a clickable copy in /Applications (path to the code baked in).
APPDST="/Applications/LocalFlow.app"
rm -rf "$APPDST" 2>/dev/null || true
if cp -R "${HERE}/LocalFlow.app" "$APPDST" 2>/dev/null; then
  sed -i '' "s#__LOCALFLOW_HOME__#${HERE}#g" "$APPDST/Contents/MacOS/LocalFlow"
  chmod +x "$APPDST/Contents/MacOS/LocalFlow"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APPDST" 2>/dev/null || true
  echo "Clickable app: ${APPDST}  (also in Launchpad / Spotlight)"
else
  echo "Note: couldn't copy to /Applications; use ${HERE}/LocalFlow.app"
fi

echo
echo "LocalFlow installed — starts at login, and is running now."
echo "Menu-bar item: 'LF' near the right of the menu bar (after ~2s)."
echo
echo "Grant these to 'Python' when macOS asks (or add it in"
echo "System Settings > Privacy & Security):"
echo "  • Microphone        (to hear you)"
echo "  • Input Monitoring  (to detect the hotkey)"
echo "  • Accessibility     (to paste text)"
echo
echo "Logs: ${HERE}/localflow.log      Control: localflow {start|stop|restart|status}"
