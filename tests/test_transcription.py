import math
import wave
from io import BytesIO

import pytest

from backend.transcription import TranscriptionError, TranscriptionService


def make_wav_bytes(*, duration_seconds: float = 0.25, sample_rate: int = 16000) -> bytes:
    frame_count = max(1, int(duration_seconds * sample_rate))
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(8000 * math.sin((2 * math.pi * 220 * index) / sample_rate))
            frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


class FakeModel:
    def __init__(self, result: object = "refund order one zero zero one") -> None:
        self.result = result
        self.calls: list[str] = []

    def recognize(self, path: str) -> object:
        self.calls.append(path)
        return self.result


def test_transcription_service_returns_transcript_and_metadata() -> None:
    model = FakeModel(result={"text": "refund my hoodie"})
    service = TranscriptionService(loader=lambda _: model)

    result = service.transcribe_bytes(
        audio_bytes=make_wav_bytes(),
        filename="voice-note.wav",
        content_type="audio/wav",
    )

    assert result.transcript == "refund my hoodie"
    assert result.provider == "onnx_asr"
    assert result.model_name == "nemo-parakeet-tdt-0.6b-v3"
    assert result.duration_ms is not None
    assert result.latency_ms >= 1
    assert len(model.calls) == 1


def test_transcription_service_rejects_empty_audio() -> None:
    service = TranscriptionService(loader=lambda _: FakeModel())

    with pytest.raises(TranscriptionError, match="empty"):
        service.transcribe_bytes(audio_bytes=b"", filename="voice-note.wav", content_type="audio/wav")


def test_transcription_service_rejects_non_wav_audio() -> None:
    service = TranscriptionService(loader=lambda _: FakeModel())

    with pytest.raises(TranscriptionError, match="Only WAV"):
        service.transcribe_bytes(
            audio_bytes=b"not-audio",
            filename="voice-note.mp3",
            content_type="audio/mpeg",
        )


def test_transcription_service_rejects_audio_over_duration_limit() -> None:
    service = TranscriptionService(loader=lambda _: FakeModel(), max_duration_seconds=1)

    with pytest.raises(TranscriptionError, match="too long"):
        service.transcribe_bytes(
            audio_bytes=make_wav_bytes(duration_seconds=1.5),
            filename="voice-note.wav",
            content_type="audio/wav",
        )
