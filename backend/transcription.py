from __future__ import annotations

import io
import os
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class TranscriptionError(RuntimeError):
    """Raised when audio transcription cannot be completed."""


@dataclass
class TranscriptionResult:
    transcript: str
    provider: str
    model_name: str
    language: str | None
    latency_ms: int
    duration_ms: int | None
    warnings: list[str]


class TranscriptionService:
    def __init__(
        self,
        *,
        provider: str | None = None,
        model_name: str | None = None,
        language: str | None = None,
        max_duration_seconds: int | None = None,
        enabled: bool | None = None,
        loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.provider = provider or os.getenv("STT_PROVIDER", "onnx_asr")
        self.model_name = model_name or os.getenv("STT_MODEL", "nemo-parakeet-tdt-0.6b-v3")
        self.language = language or os.getenv("STT_LANGUAGE", "en")
        self.max_duration_seconds = max_duration_seconds or int(
            os.getenv("STT_MAX_DURATION_SECONDS", "20")
        )
        self.enabled = enabled if enabled is not None else os.getenv("STT_ENABLED", "true").lower() == "true"
        self._loader = loader
        self._model: Any | None = None

    def transcribe_bytes(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> TranscriptionResult:
        if not self.enabled:
            raise TranscriptionError("Voice transcription is disabled.")
        if not audio_bytes:
            raise TranscriptionError("Audio upload is empty.")
        if not self._is_supported_audio(filename=filename, content_type=content_type):
            raise TranscriptionError("Only WAV voice notes are supported in v1.")

        duration_ms = self._get_duration_ms(audio_bytes)
        if duration_ms is not None and duration_ms > self.max_duration_seconds * 1000:
            raise TranscriptionError(
                f"Voice note is too long. Maximum supported duration is {self.max_duration_seconds} seconds."
            )

        model = self._get_model()
        started_at = time.perf_counter()
        transcript = self._recognize_with_tempfile(model=model, audio_bytes=audio_bytes)
        latency_ms = max(1, round((time.perf_counter() - started_at) * 1000))

        if not transcript.strip():
            raise TranscriptionError("No speech was detected in the recording.")

        return TranscriptionResult(
            transcript=transcript.strip(),
            provider=self.provider,
            model_name=self.model_name,
            language=self.language,
            latency_ms=latency_ms,
            duration_ms=duration_ms,
            warnings=[],
        )

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self.provider != "onnx_asr":
            raise TranscriptionError(f"Unsupported STT provider: {self.provider}")

        loader = self._loader
        if loader is None:
            try:
                import onnx_asr  # type: ignore
            except ImportError as exc:
                raise TranscriptionError(
                    "Local speech-to-text dependency is not installed. Install requirements and retry."
                ) from exc
            loader = onnx_asr.load_model

        try:
            self._model = loader(self.model_name)
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"Could not load STT model '{self.model_name}'.") from exc
        return self._model

    def _recognize_with_tempfile(self, *, model: Any, audio_bytes: bytes) -> str:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                handle.write(audio_bytes)
                temp_path = Path(handle.name)
            result = model.recognize(str(temp_path))
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError("Local transcription failed.") from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
        return self._coerce_transcript(result)

    def _coerce_transcript(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            for key in ("text", "transcript"):
                value = result.get(key)
                if isinstance(value, str):
                    return value
        text_value = getattr(result, "text", None)
        if isinstance(text_value, str):
            return text_value
        return str(result or "")

    def _is_supported_audio(self, *, filename: str, content_type: str | None) -> bool:
        normalized_name = filename.lower()
        normalized_type = (content_type or "").lower()
        return normalized_name.endswith(".wav") or normalized_type in {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
        }

    def _get_duration_ms(self, audio_bytes: bytes) -> int | None:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                frame_rate = wav_file.getframerate()
                if frame_rate <= 0:
                    return None
                return round((frame_count / frame_rate) * 1000)
        except wave.Error:
            raise TranscriptionError("Voice note must be a valid WAV recording.")
