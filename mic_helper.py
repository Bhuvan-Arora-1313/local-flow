"""Microphone capture in its own process (spawned by recorder.py).

Why a separate process: on macOS, PortAudio's Pa_StopStream can deadlock
against CoreAudio's IO thread (both wait on the same HAL mutex). Inside
LocalFlow that froze the mic-control thread forever -- every later dictation
silently did nothing until a restart. A stuck *process*, though, can simply
be killed: the OS releases the mic, and LocalFlow already holds every block
of audio this helper sent before it hung.

Each helper runs at most ONE recording and then exits, so every dictation
gets a fresh PortAudio (and a fresh view of which mic is the default, e.g.
after AirPods connect).

Protocol
  stdin  (text lines):  "start <sample_rate>" | "stop"
  stdout (binary):      5-byte header struct("<cI") = (kind, length), payload
      R  ready (audio library loaded)       A  float32 mono audio block
      X  stopped (no more audio follows)    E  error message (utf-8)
"""
import os
import queue
import struct
import sys
import threading
import time

_out = sys.stdout.buffer
_q: queue.Queue = queue.Queue()


def _writer():
    while True:
        kind, payload = _q.get()
        try:
            _out.write(struct.pack("<cI", kind, len(payload)) + payload)
            _out.flush()
        except Exception:
            os._exit(0)          # LocalFlow went away
        if kind == b"X":
            os._exit(0)          # one recording per helper


def _watch_parent(ppid):
    # if LocalFlow dies (even while we're stuck in the audio driver), never
    # linger holding the microphone
    while True:
        time.sleep(1.0)
        if os.getppid() != ppid:
            os._exit(0)


def main():
    threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()
    threading.Thread(target=_writer, daemon=True).start()
    try:
        import sounddevice as sd
    except Exception as e:
        _q.put((b"E", f"audio library failed to load: {e}".encode()))
        _q.put((b"X", b""))
        time.sleep(5)
        return

    def callback(indata, frames, time_info, status):
        _q.put((b"A", indata.reshape(-1).astype("float32").tobytes()))

    _q.put((b"R", b""))
    stream = None
    for line in sys.stdin:
        cmd = line.split()
        if not cmd:
            continue
        if cmd[0] == "start" and stream is None:
            try:
                stream = sd.InputStream(samplerate=int(cmd[1]), channels=1, dtype="float32",
                                        blocksize=0, callback=callback)
                stream.start()
            except Exception as e:
                _q.put((b"E", str(e).encode()))
                _q.put((b"X", b""))
                break
        elif cmd[0] == "stop":
            if stream is not None:
                try:
                    stream.stop()    # <- the call that can deadlock; LocalFlow
                    stream.close()   #    kills us if the "X" never arrives
                except Exception:
                    pass
            _q.put((b"X", b""))
            break
    time.sleep(5)   # the writer exits the process once "X" is flushed
    os._exit(0)


if __name__ == "__main__":
    main()
