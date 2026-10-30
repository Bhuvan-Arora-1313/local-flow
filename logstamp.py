"""Prefix every line LocalFlow prints (stdout/stderr -> localflow.log) with a
wall-clock time, so a hang can be placed in time: what happened, in what
order, and how long it sat there."""
import sys
import time


class _Stamped:
    def __init__(self, stream):
        self._s = stream
        self._at_line_start = True

    def write(self, text):
        if not text:
            return 0
        out = []
        for chunk in text.splitlines(keepends=True):
            if self._at_line_start:
                out.append(time.strftime("%Y-%m-%d %H:%M:%S "))
            out.append(chunk)
            self._at_line_start = chunk.endswith("\n")
        self._s.write("".join(out))
        return len(text)

    def flush(self):
        self._s.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


def install():
    sys.stdout = _Stamped(sys.stdout)
    sys.stderr = _Stamped(sys.stderr)
