# LocalFlow — a free, on-device Wispr Flow

Hold a key, talk, release. Your speech is transcribed **entirely on your Mac** (Apple
GPU via MLX), cleaned up by a **local LLM** that knows your jargon, and pasted where
your cursor is. No account, no credits, no network.

```
 mic  ─►  Parakeet-TDT (MLX, on-GPU)  ─►  dictionary + acronym fixes  ─►  local LLM cleanup (Ollama)  ─►  paste at cursor
                ~0.3–0.8 s                        instant                        ~0.5–2 s
```

While you talk, a tiny **island** appears near the bottom of the screen showing a live
spectrum of your voice, and disappears when you're done.

---

## What you get vs. Wispr Flow

| | Wispr Flow | LocalFlow |
|---|---|---|
| Transcription | cloud | local (Parakeet-TDT-0.6b, MLX) |
| Jargon / names | learned dictionary | `dictionary.txt` (~1,900 terms) + local LLM cleanup |
| Filler-word removal, punctuation, self-corrections | yes | yes (LLM pass) |
| Live waveform island | yes | yes |
| Paste anywhere | yes | yes (clipboard + ⌘V) |
| Menu-bar app, launch at login | yes | yes |
| Cost / limits | free tier is capped | unlimited, offline |
| Latency | ~1 s | ~1–3 s (first use after idle: +2 s to wake the LLM) |

---

## Requirements

- **Apple Silicon Mac** — M1 / M2 / M3 / M4. Intel Macs are **not supported** (the
  speech model needs Apple's MLX / GPU).
- **macOS 12 or newer.**
- **~2 GB free disk** (Python environment + speech model).
- That's it. `git` and `python3` come from Apple's Command Line Tools — the first time
  you run `git`, macOS pops up an installer; click **Install**. (Or run
  `xcode-select --install` yourself.)

### The two models — and why you probably don't need Ollama

| | what it does | needed? |
|---|---|---|
| **Parakeet** (~0.6 GB) | turns your speech into text, on the GPU | **yes** — but `./setup.sh` downloads it automatically, nothing to install by hand |
| **Ollama + a small LLM** (~5 GB) | optional *cleanup pass*: fixes misheard jargon & names, removes "um / uh", tidies punctuation | **no** |

Without Ollama you still get real dictation: transcription, punctuation, your
`dictionary.txt` `=>` corrections, and acronym fixing (`l l m` → `LLM`). Ollama only
adds the extra polish. LocalFlow auto-detects it — if it isn't running, that step is
skipped silently.

To enable the cleanup pass: install **[Ollama](https://ollama.com)** (a normal Mac
app), then in a terminal:

```sh
ollama pull qwen3:8b
```

---

## Install

**1. Get the code**

```sh
git clone https://github.com/Bhuvan-Arora-1313/local-flow.git
cd local-flow
```

**2. Run setup** (one time, ~5 min, needs internet — afterwards it works offline)

```sh
./setup.sh
```

This creates an isolated Python 3.12 environment (uses `conda` if you have it,
otherwise a plain `python3` venv), installs the libraries, and downloads the
Parakeet speech model.

**3. (optional) Set up the cleanup LLM** — install Ollama, then `ollama pull qwen3:8b`
(see the table above).

**4. Start it**

```sh
./run.sh
```

Use `./run.sh` for the first runs — it stays in the terminal and prints logs so you
can see what's happening. A small **`LF`** item appears near the right end of the menu
bar (it shows `LF·` for ~1 second while the model loads, then `LF`).

**5. Grant three macOS permissions**

macOS attaches permissions to *the program that launched LocalFlow*:

- started with **`./run.sh`** → grant them to **Terminal** (or iTerm / whichever
  terminal you used)
- started with **`./install.sh`** (background app) → grant them to **LocalFlow**

Open **System Settings → Privacy & Security** and enable that app under:

| permission | why |
|---|---|
| **Microphone** | to hear you |
| **Input Monitoring** | to detect the hotkey |
| **Accessibility** | to type/paste the text |

macOS usually prompts on first use. If it doesn't, click **+** in each list and add
the app. **Quit and restart LocalFlow after granting.**

**6. Use it**

- **Hold Right Option (⌥)**, speak, **release**. The text appears at your cursor.
- Menu-bar item: `LF` ready · `● REC` recording · `LF…` transcribing · `LF !` error.
  If you can't see it, the menu bar is just crowded — hold **⌘** and drag other
  icons left to make room (or use the free [Ice](https://github.com/jordanbaird/Ice)).
- While you talk, the waveform island shows near the bottom of the screen.

**7. (recommended) Make it automatic**

```sh
./install.sh
```

This:
- **starts LocalFlow at every login** (no terminal needed ever again),
- adds a global **`localflow`** command,
- makes **`LocalFlow.app`** double-clickable — put it in your Dock or Applications
  and click it any time to (re)start LocalFlow. Permissions from step 5 then attach
  to **Python**; grant that once.

(`LocalFlow.app` is unsigned — if a launch is ever blocked, right-click it → **Open**
once.)

---

## Starting & stopping (day to day)

**Easiest stop:** click the **`LF` menu-bar item → Quit LocalFlow**, or `localflow stop`.

**From the terminal** (`./install.sh` adds a global `localflow` command; until then
run `./localflow` from the project folder):

```sh
localflow start      # launch in the background (no terminal window kept open)
localflow stop       # quit it
localflow restart    # after editing config.json / code
localflow status     # running? and whether it starts at login
localflow logs       # live log (Ctrl-C to stop watching)
localflow install    # enable start-at-login
localflow uninstall  # disable start-at-login
```

`localflow start` and the menu-bar Quit are all you normally need. `./run.sh` is only
for the first run / debugging (it holds the terminal and prints logs live).

---

## Teaching it your jargon

Edit **`dictionary.txt`** (in the project folder), then menu bar → **Reload
dictionary** (no restart).

```
# just a term you want spelled right:
Kubernetes
Bhuvan Arora
gRPC

# a "sounds like => what I mean" correction:
cube ctl => kubectl
my sequel => MySQL
```

Ships with ~1,900 terms across formal English, AI/ML, software, data, security,
cloud, product, finance, medicine, law, science/math, linguistics and philosophy,
plus ~120 sounds-like corrections. Add your own people, product names and acronyms
at the top.

How the dictionary is used:
- **Acronyms** — spelled-out or spaced/dotted letter runs are auto-collapsed before
  the LLM: `l l m` → `LLM`, `g p u s` → `GPUs`, `R. A. G.` → `RAG`, `l l m's` →
  `LLM's`. 3+ letters always collapse; 2-letter runs (`a i`, `u x`) only if the pair
  is a known acronym. The `ACRONYMS & SHORT FORMS` section of `dictionary.txt` pins
  plural forms (`LLMs`, `APIs`, `KPIs`) and phonetic misspellings.
- **`=>` lines** — literal whole-word find/replace, applied instantly before the LLM.
  Bulletproof for terms you know get mangled a specific way.
- **Plain terms** — the full list biases the Whisper backend directly; the cleanup
  LLM gets a focused subset (`max_glossary_terms`, default 240, proper nouns /
  acronyms / product names first). Ordinary rare words ("sycophancy", "pharmaco­kinetics",
  "stare decisis") are fixed by the LLM from its own knowledge even if not listed —
  the list matters most for names it can't guess.

---

## Configuration — `config.json`

| key | default | meaning |
|---|---|---|
| `hotkey` | `alt_r` | push-to-talk key. `cmd_r`, `ctrl_r`, `f5`, `f13`, … |
| `mode` | `push_to_talk` | or `toggle` (press once to start, again to stop) |
| `asr_model` | `mlx-community/parakeet-tdt-0.6b-v3` | see "Swapping the model" |
| `cleanup_enabled` | `true` | run the local LLM cleanup pass |
| `ollama_model` | `qwen3:8b` | any model you have in `ollama list` |
| `max_glossary_terms` | `240` | dictionary terms sent to the cleanup LLM per utterance |
| `min_record_seconds` | `0.35` | ignore accidental taps shorter than this |
| `auto_paste` | `true` | `false` = just put the text on the clipboard |
| `trailing_space` | `true` | add a space after each insert |
| `sounds` | `true` | Tink / Pop / Basso cues |
| `island` | `true` | show the live-waveform island while dictating |

Toggle the LLM pass live from the menu bar (**AI cleanup**). With it off you still get
Parakeet's own punctuation + your `=>` corrections, at ~0.5 s latency.

### Swapping the model

- **Faster / lighter**: `mlx-community/parakeet-tdt-0.6b-v2` (English only).
- **Jargon-biased at the audio stage**: set `asr_model` to
  `mlx-community/whisper-large-v3-turbo` — the Whisper backend feeds your dictionary
  in as an `initial_prompt`. Slower (~2–4 s) but sometimes nails rare terms Parakeet
  misses. It downloads on first use.
- **Cleanup model**: `qwen3:8b` is a good speed/quality balance. Any model you've
  pulled with Ollama works — a bigger one (`qwen3:30b`, `gemma2:27b`) is sharper but
  adds ~1–2 s. Set `ollama_model` in `config.json` to match.

---

## Files

```
local-flow/
  flow.py            menu-bar app + hotkey + pipeline orchestration
  asr.py             Parakeet / Whisper backends (MLX)
  cleanup.py         local LLM cleanup pass (Ollama)
  dictionary.py      dictionary parser + acronym normaliser
  recorder.py        microphone capture + live spectrum (sounddevice + FFT)
  island.py          the floating bottom-screen waveform HUD (AppKit)
  inserter.py        paste-at-cursor (clipboard + ⌘V)
  config.json        settings
  dictionary.txt     your jargon  ← edit this
  mic_test.py        record 4 s and print the transcript
  setup.sh           create the Python env + download the model
  run.sh             foreground run
  install.sh         install as a login item + add the `localflow` command
  localflow          start/stop/restart/status/logs control script
  LocalFlow.app      app bundle (macOS permissions attach to this)
```

Python env: created by `setup.sh` (conda env `localflow` or `.venv`), Python 3.12 —
`parakeet-mlx`, `mlx-whisper`, `sounddevice`, `pynput`, `rumps`, `pyobjc`.

Model cache: `~/.cache/huggingface/hub/…parakeet-tdt-0.6b-v3` (~0.6 GB). After the
first download LocalFlow runs fully offline.

`island.py` can be run on its own (`"$(cat .python-path)" island.py`) to preview the
HUD for a few seconds.

---

## Troubleshooting

| symptom | fix |
|---|---|
| Nothing happens on hotkey | grant **Input Monitoring** + **Accessibility** to the launching app (Terminal, or LocalFlow), then restart it. The log shows `This process is not trusted!` until you do. |
| Records but transcript is empty | run `"$(cat .python-path)" mic_test.py` — check the `peak level`. If ~0: wrong input device, or **Microphone** denied. |
| Text doesn't paste (but menu → *Copy last transcript* works) | **Accessibility** not granted, or the target app blocks synthetic ⌘V — set `"auto_paste": false` and paste manually. |
| Cleanup pass never runs | Ollama isn't installed / running, or the model in `ollama_model` isn't pulled. `ollama list` to check. It's optional — dictation still works without it. |
| First dictation after a break is slow | Ollama unloaded the model; it reloads in ~2 s. Or set `"cleanup_enabled": false`. |
| Jargon still wrong | add it to `dictionary.txt` (use a `=>` line), menu → Reload dictionary. |
| Wrong hotkey / conflicts | change `hotkey` in `config.json`, restart. |
| `setup.sh` fails on `pip install` | your `python3` is probably 3.13+ with no prebuilt wheels — install [Miniconda](https://docs.conda.io/en/latest/miniconda.html) and re-run `./setup.sh` (it'll use conda). |

Live logs: `tail -f localflow.log` (or `localflow logs`).
