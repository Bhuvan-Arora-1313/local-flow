#!/bin/zsh
# Install LocalFlow: always-on menu-bar app, starts at login, clickable in /Applications.
set -e
HERE="${0:A:h}"

[[ -f "${HERE}/.python-path" ]] || { echo "Run ./setup.sh first (no .python-path)."; exit 1; }

chmod +x "${HERE}"/*.sh "${HERE}/localflow" 2>/dev/null || true

# Build the native launcher (embeds Python) if it isn't there yet.
LAUNCH="${HERE}/LocalFlow.app/Contents/MacOS/LocalFlow"
if ! file "$LAUNCH" 2>/dev/null | grep -q "Mach-O"; then
  "${HERE}/build-launcher.sh" || { echo "could not build launcher"; exit 1; }
fi

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

DOMAIN="gui/$(id -u)"
PLIST="${HOME}/Library/LaunchAgents/com.localflow.dictation.plist"

# stop whatever's running first
launchctl bootout "${DOMAIN}/com.localflow.dictation" 2>/dev/null || true
pkill -f "LocalFlow.app/Contents/MacOS/LocalFlow|${HERE}/flow.py" 2>/dev/null || true
sleep 1

# ONE canonical runtime bundle at /Applications (grant permissions to this one).
# The copy in the project folder is just the build output.
APP="/Applications/LocalFlow.app"
if rm -rf "$APP" 2>/dev/null && cp -R "${HERE}/LocalFlow.app" "$APP" 2>/dev/null; then
  mkdir -p "$APP/Contents/Resources"
  print -r -- "${HERE}" > "$APP/Contents/Resources/localflow_home"
  codesign --force --deep -s - "$APP" 2>/dev/null || true
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP" 2>/dev/null || true
  echo "Clickable app: ${APP}   (also in Launchpad / Spotlight)"
else
  APP="${HERE}/LocalFlow.app"
  echo "Note: couldn't write /Applications — using ${APP}"
fi
APP_EXE="${APP}/Contents/MacOS/LocalFlow"

mkdir -p "${HOME}/Library/LaunchAgents"
sed -e "s#__APP_EXE__#${APP_EXE}#g" -e "s#__LOCALFLOW_HOME__#${HERE}#g" \
    "${HERE}/com.localflow.dictation.plist" > "${PLIST}"
launchctl bootstrap "${DOMAIN}" "${PLIST}"
launchctl enable "${DOMAIN}/com.localflow.dictation" 2>/dev/null || true

echo
echo "LocalFlow is installed, running now, and will start at every login."
echo "Menu-bar item: 'LF' near the right of the menu bar (appears after ~2s)."
echo
echo "GRANT PERMISSIONS to this app:  ${APP}"
echo "  System Settings > Privacy & Security > Accessibility / Input Monitoring / Microphone"
echo "  Add ${APP} to each list and turn it ON, then:  localflow restart"
echo
echo "Logs: ${HERE}/localflow.log      Control: localflow {start|stop|restart|status}"
