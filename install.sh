#!/bin/zsh
# Install LocalFlow as an always-on menu-bar app that starts at login.
set -e
HERE="${0:A:h}"

chmod +x "${HERE}/LocalFlow.app/Contents/MacOS/LocalFlow" "${HERE}/run.sh" \
         "${HERE}/uninstall.sh" "${HERE}/localflow"

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

# Register the .app with Launch Services so TCC (permissions) sees it by name.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "${HERE}/LocalFlow.app" 2>/dev/null || true

PLIST="${HOME}/Library/LaunchAgents/com.localflow.dictation.plist"
mkdir -p "${HOME}/Library/LaunchAgents"
sed "s#__LOCALFLOW_HOME__#${HERE}#g" "${HERE}/com.localflow.dictation.plist" > "${PLIST}"

launchctl unload "${PLIST}" 2>/dev/null || true
launchctl load "${PLIST}"

echo "LocalFlow installed and started."
echo "Menu-bar icon: 🎙️  (⏳ while the model loads for ~2s)"
echo
echo "macOS will ask for permissions the first time you use the hotkey:"
echo "  • Microphone        -> allow"
echo "  • Input Monitoring  -> allow (needed to detect the hotkey)"
echo "  • Accessibility     -> allow (needed to paste text)"
echo "If a prompt doesn't appear, add 'LocalFlow' manually in:"
echo "  System Settings > Privacy & Security > {Microphone, Input Monitoring, Accessibility}"
echo
echo "Logs: ${HERE}/localflow.log"
