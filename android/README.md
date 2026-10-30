# LocalFlow Remote (Android)

A floating island that appears in any text field on your Android phone or tablet. It sends
what you say to LocalFlow on your Mac over Tailscale and types the cleaned-up text into the field.
The speech model never runs on the phone.

Setup and install steps for users are in the main [README](../README.md#dictate-from-your-phone-or-tablet).
This file is for working on the app itself.

## Build

```sh
gradle assembleIslandDebug      # the full app (floating island)
gradle assembleKeyboardDebug    # keyboard-only variant (see below)
adb install -r app/build/outputs/apk/island/debug/app-island-debug.apk
```

No Gradle wrapper is committed. Use a system Gradle (`brew install gradle`, with
`brew install openjdk@17`) or open this folder in Android Studio. `local.properties` points
at your SDK (`sdk.dir=...`) and is git-ignored.

After `adb install -r`, re-tap **Enable floating dictation** in the app. Android stops the
service when the app is replaced, and adb can't restart it.

## How it works

```
app/src/main/java/com/localflow/remote/
  MainActivity.kt                  pairing, permissions, Enable, island appearance settings
  DictationOverlayService.kt       mic foreground service + the island and live-text windows
  LocalFlowAccessibilityService.kt when to show the island; inserts text into the field
  IslandView.kt                    the island itself: idle pill, ✕ / voice bars / ✓, transcribing dots
  AudioRecorder.kt                 16 kHz mono PCM16 + live spectrum (port of the Mac's recorder.py)
  ApiClient.kt                     /v1/health, /v1/transcribe, /v1/preview on the Mac (server.py)
  Prefs.kt                         Mac address/token, island size/opacity/position, live-text toggle
  LocalFlowInputMethodService.kt   the keyboard variant's dictation keyboard
```

- **Typing into the field.** The accessibility service declares `flagInputMethodEditor`
  (Android 13+), which gives it its own `InputConnection` to the focused field alongside the
  user's real keyboard. `commitText()` there works everywhere a keyboard does: terminals,
  Samsung Notes, and fields whose placeholder `ACTION_SET_TEXT` would misread as real text. The
  node-based `ACTION_SET_TEXT` path is only a fallback for older Android.
- **When the island shows.** It shows between `onStartInput` and `onFinishInput` of that input
  method, so it stays while a field is active even with the keyboard lowered. Two exclusions:
  placeholder sessions some screens open with no view behind them (`TYPE_NULL` with
  `fieldId == -1`; Samsung's home screen does this), and a 150 ms delay before showing so
  momentary sessions don't flash it.
- **Why the mic lives in a foreground service started from the app.** On Android 14+ a
  microphone foreground service can't be *created* from the background, and a tap on an overlay
  from another app doesn't qualify as foreground. So it's created once from `MainActivity` and
  then stays running (persistent notification). Later recordings are unaffected.
- **Live voice bars.** A 512-point FFT in log-spaced bands with per-band auto-gain, gated against
  the room's noise floor (the quietest moment in the last ~2 s), mirrored around the centre like
  the Mac island.

## Build variants

| | `island` | `keyboard` |
|---|---|---|
| How you dictate | floating island in any text field | switch to the LocalFlow keyboard |
| Accessibility service | yes | no |
| Installs from a browser download | blocked by Play Protect in some regions | yes |

Both use the same `applicationId`, so either can be installed over the other.

## Gotchas found on real devices

- Google Play Protect (India, and likely other regions) blocks browser/file-manager installs of
  any app declaring an accessibility service, even with scanning off. Install over adb.
- Wireless debugging needs the device on a real Wi-Fi network. Hosting its own hotspot doesn't count.
- Android's Settings app, and some banking/UPI apps, hide all third-party overlay windows, so the
  island can't appear there.
- Samsung's package installer crashes when an APK is opened from Termux, and My Files doesn't
  list APKs copied in by Termux.
