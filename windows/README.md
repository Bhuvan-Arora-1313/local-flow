# LocalFlow for Windows

Dictate on a Windows PC with the speech model running on your Mac. Hold **Left Alt**, speak,
and let go: the audio goes to LocalFlow on the Mac over Tailscale, and the cleaned-up text is
typed wherever your cursor is. Nothing runs on the PC's GPU. It is the Windows twin of the
Android app, with the Mac's island and live-text box.

## Install (on the Windows PC)

1. Install [Tailscale](https://tailscale.com/download/windows) and sign in. The Mac must be on
   the same tailnet, or shared with this PC's Tailscale account.
2. Copy `LocalFlow.exe` anywhere, for example `Documents`, and double-click it. It's a single file with no installer
   and no .NET download.
   - SmartScreen may say *Windows protected your PC*, because the exe isn't code-signed. Click
     **More info → Run anyway**.
3. Settings opens on first run. Fill in:
   - **Mac's Tailscale address**: the Mac's `100.x.x.x` IP.
   - **Pairing token**: on the Mac, LocalFlow menu → Settings → Remote dictation.
   Click **Test connection**, then **Save**.

LocalFlow then starts with Windows and lives in the tray (bottom-right, maybe under `^`).

## Using it

| | |
|---|---|
| Hold **Left Alt** | talk; let go to type the text |
| Double-tap **Left Alt** | hands-free; tap again to stop |
| **x** on the island | cancel |
| Alt+Tab, Alt+F4 … | still work: a shortcut cancels the dictation and goes through as normal |

A bare tap of Alt no longer opens app menus (F10 still does). Right Alt or Right Ctrl can be the
hotkey instead (tray menu → Hotkey).

The tray menu also has **Paste last dictation**, and **Retry last recording** for when the Mac
couldn't be reached. Failed recordings are kept until the next one succeeds.

## How it works

```
Program.cs        single instance, starts the controller
Controller.cs     hold / double-tap / toggle logic (port of flow.py), send + paste, live preview
KeyboardHook.cs   low-level keyboard hook on its own thread; swallows a bare hotkey press,
                  replays it when it turns out to be part of a shortcut
Recorder.cs       16 kHz mono PCM16 via NAudio + the island's spectrum (port of recorder.py)
ApiClient.cs      /v1/health, /v1/transcribe, /v1/preview, /v1/restart (server.py)
Island.cs         the island, drawn like island.py
Ghost.cs          live-text box / notices above the island
Overlay.cs        never-focused, always-on-top windows on the monitor you're typing on
Inserter.cs       clipboard + Ctrl+V, then restores the clipboard (kept out of Win+V history)
Tray.cs           tray icon and menu;  SettingsWindow.cs  pairing + preferences
```

Settings and the log are in `%APPDATA%\LocalFlow\`. The log has events and errors, never the
dictated text.

## Build

Any OS with the .NET SDK (8 or newer):

```sh
cd windows
dotnet publish -c Release -o dist      # -> dist/LocalFlow.exe (self-contained, ~70 MB)
```

## Known limits

- It can't type into apps running as administrator. Windows blocks synthetic keystrokes from a
  normal app into elevated windows.
- Alt + mouse-click (no key) while holding still counts as dictation.
- Echo cancellation isn't applied, so music playing loudly from the PC's speakers can end up in the
  recording.
