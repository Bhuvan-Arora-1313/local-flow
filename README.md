# LocalFlow

**A free, on-device dictation app for Apple Silicon Macs — a local Wispr Flow.**

Hold a key, talk, release. Your speech is transcribed on your Mac's GPU, cleaned up
by a local LLM that knows your jargon, and typed wherever your cursor is. No account,
no subscription, no credits, nothing leaves your machine.

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Install](#install)
- [First run & permissions](#first-run--permissions)
- [Using it](#using-it)
- [The models & RAM — important](#the-models--ram--important)
- [Hindi / Hinglish](#hindi--hinglish)
- [Settings reference](#settings-reference)
- [Starting, stopping, updating](#starting-stopping-updating)
- [Troubleshooting](#troubleshooting)
- [How the project is laid out](#how-the-project-is-laid-out)
- [Uninstall](#uninstall)

---

## What you get

| Feature | Notes |
|---|---|
| **Push-to-talk dictation** | Hold a key, speak, release → text appears at the cursor, in any app. |
| **Double-tap to lock** | Quick double-tap the hotkey → records hands-free until you tap again. (Wispr-style.) |
| **On-screen island** | A small pill at the bottom of the screen shows a live waveform of your voice while you dictate. |
| **Jargon-aware** | A ~1,900-term dictionary + a local LLM cleanup pass fix product names, acronyms, technical words. |
| **Learn as you type** | *(opt-in)* unusual words you type get added to the dictionary automatically, with an Undo toast. |
| **Smart list formatting** | Speak "first… second… third…" and it becomes a numbered list; a lead-in + items becomes bullets. |
| **Filler & stumble removal** | Drops "um / uh / you know", repeated phrases, false starts; fixes stray commas from speech pauses. |
| **Hindi / Hinglish** | Optional Whisper model + Roman-output mode: speak Hindi, get `kya haal hai` (or Devanagari). |
| **Usage & History** | Total words, dictations, day-streak, and your recent transcripts. |
| **Menu-bar app** | Runs quietly as `LF` in the menu bar. Optional launch-at-login. |

Everything runs locally. The only network use is a one-time model download during setup.

---

## How it works

```
  ┌────────┐   ┌─────────────────────┐   ┌──────────────────────┐   ┌───────────────────┐   ┌──────────────┐
  │  mic   │──▶│  speech-to-text      │──▶│  deterministic fixes │──▶│  local LLM cleanup │──▶│ paste at cursor │
  │        │   │  Parakeet / Whisper  │   │  dedup, commas,      │   │  jargon, fillers,  │   │  (clipboard+⌘V) │
  │        │   │  (MLX, on the GPU)   │   │  acronyms, ⇒ terms   │   │  punctuation, lists│   │                 │
  └────────┘   └─────────────────────┘   └──────────────────────┘   └───────────────────┘   └──────────────┘
      ~0.3–1 s (Parakeet) / ~1–3 s (Whisper)          instant              ~1–2 s
```

1. **Speech-to-text** runs on Apple's MLX framework (your GPU):
   - **Parakeet-TDT 0.6b** — default, English + major European languages, fastest.
   - **Whisper large-v3-turbo** — optional, multilingual including Hindi.
2. **Deterministic fixes** (pure code, instant): collapse a repeated phrase, strip
   pause-commas, expand spelled-out acronyms (`l l m` → `LLM`), apply your
   `wrong ⇒ right` dictionary rules.
3. **LLM cleanup** (optional, via [Ollama](https://ollama.com)): fixes misheard
   jargon using your dictionary as the source of truth, removes fillers, fixes
   punctuation, and formats spoken lists. Skipped automatically if Ollama isn't
   running — you still get working dictation.
4. **Insert** — the text is put on the clipboard and pasted with ⌘V (works in every
   app), then your old clipboard is restored.

---

## Install

### Requirements

- **Apple Silicon Mac** — M1 / M2 / M3 / M4. **Intel Macs are not supported** (MLX needs Apple's GPU).
- **macOS 12 or newer.**
- **~2 GB free disk** for the Python environment + speech model.
- **[Ollama](https://ollama.com)** — *optional but recommended*, for the jargon
  cleanup pass. Without it you still get transcription + dictionary + acronym fixes.

### Easiest — one line

```sh
curl -fsSL https://raw.githubusercontent.com/Bhuvan-Arora-1313/local-flow/main/bootstrap.sh | bash
```

This clones the repo to `~/localflow` and runs setup. (The first time you run `git`,
macOS may pop up an installer for the Command Line Tools — click **Install**.)

### Manual

```sh
git clone https://github.com/Bhuvan-Arora-1313/local-flow.git
cd local-flow
./setup.sh
```

`setup.sh` (one time, ~5 min, needs internet):

- creates an isolated Python 3.12 environment (uses `conda` if present, else a `venv`),
- installs the libraries,
- compiles a tiny native launcher so `LocalFlow.app` is a real double-clickable app,
- downloads the Parakeet speech model (~0.6 GB).

### (optional) The cleanup LLM

```sh
# install Ollama from https://ollama.com, then:
ollama pull qwen3:8b
```

LocalFlow auto-detects Ollama. Pick any model you have from **Settings → Cleanup model**.

---

## First run & permissions

```sh
./run.sh          # runs in the foreground with logs — use this the first time
```

An `LF` item appears near the right of the menu bar (shows `LF·` for ~1 s while the
model loads).

**Grant three permissions.** LocalFlow needs macOS to let it watch the keyboard and
microphone. On first use a dialog appears — click **Open System Settings** and turn
LocalFlow on. If no dialog appears, add it by hand:

**System Settings → Privacy & Security →**

| Permission | Why |
|---|---|
| **Microphone** | to hear you |
| **Input Monitoring** | to detect the hotkey |
| **Accessibility** | to type / paste the text |

Then **quit LocalFlow and open it again** — the trust check only runs at startup.

> Permissions attach to whatever launched it: `./run.sh` from a terminal → grant them
> to **Terminal**; the installed app → grant them to **LocalFlow** / **Python**.

---

## Using it

- **Hold Left Option (⌥)**, speak, **release**. Text lands at your cursor.
- For a longer dictation: **double-tap** Left Option → it locks and records
  hands-free → **tap once more** to stop and transcribe.
- The waveform island shows at the bottom of the screen while you talk.
- Menu-bar `LF` states: `LF` ready · `● REC` recording · `LF…` transcribing.

The hotkey and recording style are configurable in **Settings**.

### Teaching it your words

**Settings → Dictionary** has a live editor. One entry per line:

```
# a term you want spelled/capitalised right:
Kubernetes
Bhuvan Arora
gRPC

# a "sounds-like ⇒ what I meant" correction (applied instantly, before the LLM):
cube ctl => kubectl
my sequel => MySQL
```

Turn on **Learn new words as I type** and any unusual word you type twice is added
automatically — a small toast above the island shows `Added "word"` with an **Undo**
button.

---

## The models & RAM — important

LocalFlow can use up to **three** models. Only load what you need.

| Model | Job | Size in RAM | Loaded when |
|---|---|---|---|
| **Parakeet-TDT 0.6b** *(or Whisper large-v3-turbo)* | speech → text | ~0.6 GB *(Whisper ~1.5 GB)* | always (it's the core) |
| **Cleanup LLM** — `qwen3:8b` by default | fix jargon, fillers, punctuation, lists | ~6 GB *(varies by model)* | when **AI cleanup** is on |
| **Hindi model** — `gemma3:4b` by default | romanise Devanagari → Hinglish | ~3 GB | **only when you actually dictate Hindi** |

### Controlling RAM

- **English only?** Leave *Hindi text as* = **Devanagari** (or just never speak
  Hindi). The Hindi model **never loads** — you only pay for the speech model + the
  cleanup LLM.
- **Want the smallest footprint?** In **Settings**, set both *Cleanup model* and
  *Hindi model* to a small model like `gemma3:4b` (~3 GB) or `llama3.2:3b` (~2 GB).
  Cleanup quality drops a little; RAM drops a lot.
- **Don't want the LLM at all?** Turn off **AI cleanup**. You still get transcription,
  punctuation from the speech model, your `⇒` dictionary rules, and acronym fixing —
  at ~0.5 s and near-zero extra RAM.
- **`Keep the AI model always loaded`** *(Settings, on by default)* — keeps the
  cleanup model resident so there's no ~15 s wake-up lag after an idle period. Turn
  it **off** to let Ollama free that RAM when you're not dictating (you'll wait a few
  seconds on the next dictation while it reloads).

### Typical setups

| You want… | Cleanup model | Hindi model | Roughly |
|---|---|---|---|
| Fast English, best quality | `qwen3:8b` | *(none)* | speech model + ~6 GB |
| Smallest RAM, still good | `gemma3:4b` | `gemma3:4b` | speech model + ~3 GB |
| Tiny | `llama3.2:3b` | `llama3.2:3b` | speech model + ~2 GB |
| No LLM at all | — (AI cleanup off) | — | just the speech model |
| English + Hindi (Roman) | `qwen3:8b` | `gemma3:4b` | speech model + ~9 GB (both) |

---

## Hindi / Hinglish

Speak Hindi and get it back in **Roman letters** (`kya haal hai`) or **Devanagari**
(`क्या हाल है`) — your choice.

**Settings → Keys & models:**

1. **Speech model** → `Whisper large-v3-turbo` (multilingual; downloads ~1.5 GB the
   first time).
2. **Language** → `Hindi / Hinglish` (or `Auto-detect`).
3. **Hindi text as** → `Roman / Hinglish` or `Devanagari`.

**How it works:** Whisper transcribes Hindi accurately in Devanagari, then a small
dedicated model (`gemma3:4b` by default) transliterates it to casual Roman Hindi,
keeping English words as English. It's fast (~1 s) and only loads while you're
actually dictating Hindi.

> Romanisation is ~85% clean with `gemma3:4b` — the occasional word slips. For the
> best quality you can point *Hindi model* at a larger Indic model (e.g. Sarvam-M),
> at the cost of RAM. For pure-English sessions, switch the speech model back to
> **Parakeet** — it's faster.

---

## Settings reference

Open with the menu-bar `LF` → **Settings…** (or ⌘,). Changes to toggles, models and
dictionary apply immediately; **hotkey / recording style / speech model** take effect
after you restart LocalFlow.

| Setting | What it does |
|---|---|
| **Start LocalFlow at login** | installs/removes a launch agent |
| **AI cleanup** | run the local LLM pass (needs Ollama) |
| **Smart formatting** | spoken enumerations → numbered / bulleted lists |
| **Keep the AI model always loaded** | no wake-up lag; uses that model's RAM while idle |
| **Show the waveform island** | the bottom-of-screen pill |
| **Play start / done sounds** | Tink / Pop cues |
| **Paste automatically** | off = just copy to clipboard |
| **Add a space after each dictation** | |
| **Show notifications** | |
| **Learn new words as I type** | auto-add unusual typed words to the dictionary |
| **Hotkey** | Right/Left Option, ⌘, ⌃, ⇧, F5–F19 |
| **Recording style** | hold-or-lock · hold-only · toggle |
| **Speech model** | Parakeet (English) or Whisper (multilingual) |
| **Language** | for Whisper: auto / English / Hindi / … |
| **Hindi text as** | Devanagari or Roman/Hinglish |
| **Cleanup model** | any model from your `ollama list` |
| **Hindi model** | model for Devanagari→Roman, or "(none)" |
| **Ollama model** *(usage/history)* | — |
| **Dictionary editor** | edit terms & `⇒` rules; Save reloads live |
| **Usage & History** | totals, streak, recent transcripts |

---

## Starting, stopping, updating

`./install.sh` adds a global **`localflow`** command and starts it at login (and
copies a clickable **`/Applications/LocalFlow.app`**).

```sh
localflow start      # run in the background
localflow stop       # quit it   (or menu-bar LF → Quit LocalFlow)
localflow restart    # after editing config / code
localflow status     # running? starts at login?
localflow logs       # live log (Ctrl-C to stop watching)
localflow install    # enable start-at-login
localflow uninstall  # disable start-at-login
```

Day to day: `localflow start` and the menu-bar **Quit** are all you need. `./run.sh`
is only for the first run / debugging.

**Update:** `cd ~/localflow && git pull && localflow restart` — or just re-run the
one-line installer.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Menu-bar `LF` doesn't appear | you launched it in a way macOS treats as background-only. Use `localflow start` or open `/Applications/LocalFlow.app`. |
| Nothing happens on the hotkey | grant **Input Monitoring** + **Accessibility**, then **restart** LocalFlow. Log shows `AXIsProcessTrusted = False` until you do. |
| Records but transcript is empty | wrong input device or **Microphone** denied. Check `~/localflow/localflow.log`. |
| Text doesn't paste (menu → *Copy last transcript* works) | **Accessibility** not granted, or the app blocks synthetic ⌘V — set *Paste automatically* off and paste by hand. |
| First dictation after a break is slow | the cleanup model was unloaded. Turn on **Keep the AI model always loaded**. |
| Cleanup pass never runs | Ollama isn't running, or the chosen model isn't pulled. `ollama list` to check. It's optional. |
| Uses too much RAM | see [The models & RAM](#the-models--ram--important) — turn off the Hindi mode, pick a smaller cleanup model, or turn off *Keep the AI model always loaded*. |
| Hindi comes out as Devanagari | Settings → **Hindi text as → Roman / Hinglish** (needs AI cleanup on). |
| `setup.sh` fails on `pip install` | your `python3` is too new for the wheels — install [Miniconda](https://docs.conda.io/en/latest/miniconda.html) and re-run `./setup.sh`. |

Logs: `tail -f ~/localflow/localflow.log` (or `localflow logs`).

---

## How the project is laid out

```
local-flow/
  flow.py            menu-bar app + hotkey + pipeline orchestration (AppKit)
  asr.py             Parakeet / Whisper speech-to-text (MLX)
  cleanup.py         local LLM cleanup pass + Hindi transliteration (Ollama)
  dictionary.py      dictionary parser, acronym + comma + repeat normalisers
  recorder.py        microphone capture + live spectrum for the island
  island.py          the floating waveform island + the "learned word" toast
  learn.py           opt-in learn-as-you-type
  usage.py           usage stats + the Usage & History window
  settings.py        the native Settings window
  inserter.py        paste-at-cursor
  launcher.c         compiled bundle entry point (embeds Python)
  config.default.json   shipped defaults  (your live settings live in config.json, git-ignored)
  dictionary.txt        the vocabulary  (edit via Settings)
  setup.sh / build-launcher.sh / install.sh / uninstall.sh / run.sh / localflow / bootstrap.sh
  LocalFlow.app         the app bundle
```

Nothing is sent anywhere. Models are cached under `~/.cache/huggingface`; after the
first download LocalFlow runs fully offline.

---

## Uninstall

```sh
cd ~/localflow
./uninstall.sh            # stop it, remove from login items, remove /Applications/LocalFlow.app
rm -rf ~/localflow        # remove the app
# optional: remove the Python env and models
conda env remove -n localflow      # or: rm -rf ~/localflow/.venv
rm -rf ~/.cache/huggingface/hub/models--mlx-community--parakeet-tdt-0.6b-v3
```

Also remove **LocalFlow** from System Settings → Privacy & Security (Microphone /
Input Monitoring / Accessibility).

---

## License

MIT — see [LICENSE](LICENSE).
