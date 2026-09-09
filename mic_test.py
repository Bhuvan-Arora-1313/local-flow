#!/usr/bin/env python3
"""Quick check that the microphone works and the ASR pipeline is sane.
Records 4 seconds, transcribes, prints the result. Run: ./mic_test.py"""
import sys, time, json, os
import numpy as np
import sounddevice as sd

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json")))

print("Input devices:")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(f"  [{i}] {d['name']}  (default in: {sd.default.device[0] == i})")

SECS = 4
sr = CFG["sample_rate"]
print(f"\nRecording {SECS}s — say something with jargon in it…")
time.sleep(0.4)
audio = sd.rec(int(SECS * sr), samplerate=sr, channels=1, dtype="float32")
sd.wait()
audio = audio.reshape(-1)
peak = float(np.max(np.abs(audio)))
print(f"captured {len(audio)/sr:.1f}s, peak level {peak:.3f} " + ("(OK)" if peak > 0.01 else "(SILENT? check mic permission / input device)"))

from asr import Transcriber
import dictionary as dictmod
from cleanup import Cleaner

asr = Transcriber(CFG["asr_model"], sr)
raw = asr.transcribe(audio)
terms, corr = dictmod.load(os.path.join(BASE, "dictionary.txt"))
fixed = dictmod.apply_literal_corrections(raw, corr)
cl = Cleaner(CFG["ollama_url"], CFG["ollama_model"], CFG["cleanup_timeout_seconds"])
final = cl.clean(fixed, terms) if cl.available() else fixed
print("\nRAW  :", raw)
print("FINAL:", final)
