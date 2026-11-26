"""Local speech-to-text on Apple MLX (runs on the GPU).

Two backends, chosen by the model id:
  * Parakeet-TDT  - fastest, English + major European langs, auto punctuation.
                    No language option; `language` is ignored.
  * Whisper       (id contains "whisper") - multilingual incl. Hindi / Hinglish,
                    accepts an `initial_prompt` (the jargon glossary) and a
                    `language` ("auto" = detect, "en", "hi", …).
"""
import time
import numpy as np


class _ParakeetBackend:
    # A single non-chunked pass costs more than linear time/memory in audio
    # length (the conformer encoder's self-attention), so a long or runaway
    # recording can turn into a multi-minute decode that looks like a hang
    # and pins the GPU. Past CHUNK_S, split it the same way the library's own
    # file-based .transcribe(chunk_duration=...) does for long files.
    CHUNK_S = 45.0
    OVERLAP_S = 8.0

    def __init__(self, model_id: str, sample_rate: int, language: str = "auto",
                 romanize_hindi: bool = False):
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel
        from parakeet_mlx.alignment import (
            merge_longest_common_subsequence, merge_longest_contiguous,
            sentences_to_result, tokens_to_sentences,
        )
        self._mx = mx
        self._get_logmel = get_logmel
        self._merge_contiguous = merge_longest_contiguous
        self._merge_lcs = merge_longest_common_subsequence
        self._tokens_to_sentences = tokens_to_sentences
        self._sentences_to_result = sentences_to_result
        self.model = from_pretrained(model_id)
        self.sample_rate = int(getattr(self.model.preprocessor_config, "sample_rate", sample_rate))

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        if len(audio) / self.sample_rate <= self.CHUNK_S:
            mel = self._get_logmel(self._mx.array(audio), self.model.preprocessor_config)
            return self.model.generate(mel)[0].text.strip()

        chunk_n = int(self.CHUNK_S * self.sample_rate)
        overlap_n = int(self.OVERLAP_S * self.sample_rate)
        hop = self.model.preprocessor_config.hop_length
        all_tokens = []
        for start in range(0, len(audio), chunk_n - overlap_n):
            end = min(start + chunk_n, len(audio))
            if end - start < hop:
                break
            mel = self._get_logmel(self._mx.array(audio[start:end]), self.model.preprocessor_config)
            chunk_tokens = self.model.generate(mel)[0].tokens
            offset = start / self.sample_rate
            for tok in chunk_tokens:
                tok.start += offset
                tok.end = tok.start + tok.duration
            if all_tokens:
                try:
                    all_tokens = self._merge_contiguous(
                        all_tokens, chunk_tokens, overlap_duration=self.OVERLAP_S)
                except RuntimeError:
                    all_tokens = self._merge_lcs(
                        all_tokens, chunk_tokens, overlap_duration=self.OVERLAP_S)
            else:
                all_tokens = chunk_tokens
        return self._sentences_to_result(self._tokens_to_sentences(all_tokens)).text.strip()


class _WhisperBackend:
    # Whisper has no real "output script" switch, but it takes the style of
    # whatever initial_prompt you give it -- primed with a romanized-Hindi
    # example, it decodes code-mixed speech directly as romanized Hinglish
    # in one pass, instead of Devanagari that a separate LLM pass then has
    # to transliterate (that second pass was the actual source of garbled
    # spelling and outright mistranslation reported with hindi_script=latin).
    HINGLISH_PRIMER = "Mujhe kal office jana hai aur meeting attend karni hai, kyunki kaafi important hai."

    def __init__(self, model_id: str, sample_rate: int, language: str = "auto",
                 romanize_hindi: bool = False):
        import mlx_whisper
        self._mw = mlx_whisper
        self.model_id = model_id
        self.sample_rate = 16000
        self.language = (language or "auto").lower()
        self.romanize_hindi = romanize_hindi

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        # Keep Whisper's prompt SHORT. A long dictionary dump in initial_prompt
        # makes it garble Hindi (stray commas, half-romanised words) and can
        # tip it into repetition loops. The dictionary is still applied by
        # the corrections + cleanup steps after transcription.
        if self.romanize_hindi:
            prompt = self.HINGLISH_PRIMER      # tested: primer alone beats primer + terms
        elif prompt and len(prompt) > 200:
            prompt = prompt[:200].rsplit(",", 1)[0]
        lang = None if self.language in ("auto", "", "detect") else self.language
        if lang is None and self.romanize_hindi:
            # Hinglish speaker: always decode as Hindi. Whisper's language
            # guess was useless on real Hinglish (a mostly-Hindi sentence
            # scored 1-3% Hindi, "thumbs up emoji" 51%), and decoding Hindi
            # speech as English TRANSLATES it ("mazaak" -> "mzak or that is
            # more realistic"). Primed with romanised Hinglish, Hindi mode
            # keeps English words in English -- tested word-for-word on the
            # English bench clips -- and skips the detection pass (~0.4s).
            lang = "hi"
        elif lang is None:
            self._install_hindi_bias()
        out = self._mw.transcribe(
            audio,
            path_or_hf_repo=self.model_id,
            language=lang,
            initial_prompt=prompt or None,
            fp16=True,
            condition_on_previous_text=False,
        )
        return out.get("text", "").strip()


    # Whisper picks ONE language per utterance by plain majority. Hinglish
    # that starts in English ("this is better and ab main kaafi kuch kar
    # sakta hoon") then gets decoded as English and the Hindi part comes out
    # as nonsense ("abe kaufi kuch kar saktatau"). Pure English scores Hindi
    # at ~0.000 (measured on the bench clips) and Hindi at ~0.96, so any
    # real Hindi share is a clear signal: decode it as Hindi, which keeps the
    # English words in Latin script anyway. Urdu counts as Hindi -- spoken
    # they're the same, and decoding as "ur" would output Arabic script.
    HINDI_SHARE = 0.10

    def _install_hindi_bias(self):
        """Applies HINDI_SHARE inside Whisper's own language detection (which
        transcribe() runs anyway), so it costs no extra model pass."""
        try:
            import mlx.core as mx
            from mlx_whisper.transcribe import ModelHolder
            model = ModelHolder.get_model(self.model_id, mx.float16)
        except Exception as e:
            print(f"[asr] couldn't set up Hindi detection ({e})")
            return
        if getattr(model, "_lf_hindi_bias", False):
            return
        orig = model.detect_language
        share = self.HINDI_SHARE

        def detect_language(mel, tokenizer=None):
            tokens, probs = orig(mel, tokenizer)
            if isinstance(probs, dict):
                hindi = probs.get("hi", 0.0) + probs.get("ur", 0.0)
                if hindi >= 0.01:
                    print(f"[asr] hindi share {hindi:.2f}, english {probs.get('en', 0.0):.2f}"
                          f" -> {'hi' if hindi >= share else max(probs, key=probs.get)}")
                if hindi >= share:
                    probs = dict(probs, hi=1.0)
            return tokens, probs

        model.detect_language = detect_language
        model._lf_hindi_bias = True


class Transcriber:
    # MLX's allocator keeps freed GPU buffers around for reuse instead of
    # returning them to the OS, bucketed by size. Real dictations/meeting
    # chunks are all different lengths, so over a day of varied use this
    # cache keeps growing (we measured ~5GB from a couple hundred calls with
    # no cap, climbing further the longer the process runs) until the app
    # has to be killed. Capping it keeps RSS flat with no measurable latency
    # cost -- it just reuses whatever's within the cap instead of hoarding.
    MLX_CACHE_LIMIT_MB = 512

    def __init__(self, model_id: str, sample_rate: int = 16000, language: str = "auto",
                 romanize_hindi: bool = False):
        try:
            import mlx.core as mx
            mx.set_cache_limit(self.MLX_CACHE_LIMIT_MB * 1024 * 1024)
        except Exception as e:
            print(f"[asr] couldn't set MLX cache limit: {e}")
        self.model_id = model_id
        t0 = time.time()
        BE = _WhisperBackend if "whisper" in model_id.lower() else _ParakeetBackend
        self.backend = BE(model_id, sample_rate, language, romanize_hindi)
        self.sample_rate = self.backend.sample_rate
        try:
            self.transcribe(np.zeros(self.sample_rate // 2, dtype=np.float32))
        except Exception:
            pass
        print(f"[asr] loaded {model_id} in {time.time() - t0:.1f}s "
              f"(sr={self.sample_rate}, lang={language})")

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        """audio: mono float32 PCM in [-1, 1] at self.sample_rate."""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio = np.ascontiguousarray(audio.reshape(-1))
        if audio.size < self.sample_rate // 20:  # < 50 ms
            return ""
        return self.backend.transcribe(audio, prompt)
