"""Local speech-to-text on Apple MLX (runs on the GPU).

Two backends, chosen by the model id in config.json:
  * Parakeet-TDT  (default) - fastest, great on technical English, auto punctuation.
  * Whisper       (any id containing "whisper") - accepts an `initial_prompt`, so the
                  jargon glossary can bias recognition at the audio stage.
"""
import time
import numpy as np


class _ParakeetBackend:
    def __init__(self, model_id: str, sample_rate: int):
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel
        self._mx = mx
        self._get_logmel = get_logmel
        self.model = from_pretrained(model_id)
        self.sample_rate = int(getattr(self.model.preprocessor_config, "sample_rate", sample_rate))

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        mel = self._get_logmel(self._mx.array(audio), self.model.preprocessor_config)
        return self.model.generate(mel)[0].text.strip()


class _WhisperBackend:
    def __init__(self, model_id: str, sample_rate: int):
        import mlx_whisper
        self._mw = mlx_whisper
        self.model_id = model_id
        self.sample_rate = 16000

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        # Whisper's decoder prompt is capped near 224 tokens; a long glossary would
        # be truncated and could bias badly. Keep it to a safe leading slice.
        if prompt and len(prompt) > 800:
            prompt = prompt[:800].rsplit(",", 1)[0]
        out = self._mw.transcribe(
            audio,
            path_or_hf_repo=self.model_id,
            language="en",
            initial_prompt=prompt or None,
            fp16=True,
            condition_on_previous_text=False,
        )
        return out.get("text", "").strip()


class Transcriber:
    def __init__(self, model_id: str, sample_rate: int = 16000):
        self.model_id = model_id
        t0 = time.time()
        if "whisper" in model_id.lower():
            self.backend = _WhisperBackend(model_id, sample_rate)
        else:
            self.backend = _ParakeetBackend(model_id, sample_rate)
        self.sample_rate = self.backend.sample_rate
        try:
            self.transcribe(np.zeros(self.sample_rate // 2, dtype=np.float32))
        except Exception:
            pass
        print(f"[asr] loaded {model_id} in {time.time() - t0:.1f}s (sr={self.sample_rate})")

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        """audio: mono float32 PCM in [-1, 1] at self.sample_rate."""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.ascontiguousarray(audio.reshape(-1))
        if audio.size < self.sample_rate // 20:  # < 50 ms
            return ""
        return self.backend.transcribe(audio, prompt)
