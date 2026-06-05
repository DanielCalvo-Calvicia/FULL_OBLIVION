from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True, slots=True)
class ExternalHealthResponseDto:
    is_available: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MicrophoneStreamRequestDto:
    sample_rate: int = 16000
    chunk_size: int = 1024


@dataclass(frozen=True, slots=True)
class MicrophoneStreamResponseDto:
    audio_stream: AsyncIterator[bytes]
    sample_rate: int = 16000


@dataclass(frozen=True, slots=True)
class STTSetStreamRequestDto:
    audio_stream: AsyncIterator[bytes]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class STTTextStreamRequestDto:
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class STTStreamResponseDto:
    text_stream: AsyncIterator[bytes]


@dataclass(frozen=True, slots=True)
class STTBatchRequestDto:
    audio_data: bytes
    sample_rate: int = 16000


@dataclass(frozen=True, slots=True)
class STTBatchResponseDto:
    text: str


@dataclass(frozen=True, slots=True)
class TTSSetStreamRequestDto:
    text: str
    sample_rate: int = 24000
    channels: int = 1


@dataclass(frozen=True, slots=True)
class TTSTextStreamRequestDto:
    text_stream: AsyncIterator[bytes]
    sample_rate: int = 24000
    channels: int = 1


@dataclass(frozen=True, slots=True)
class TTSAudioStreamRequestDto:
    sample_rate: int = 24000
    channels: int = 1
    keep_open_after_completed: bool = True
    completed_outputs_to_read: int | None = None


@dataclass(frozen=True, slots=True)
class TTSAudioStreamResponseDto:
    audio_stream: AsyncIterator[bytes]


@dataclass(frozen=True, slots=True)
class SpeakerPlaybackRequestDto:
    audio_stream: AsyncIterator[bytes]
    sample_rate: int = 24000
    channels: int = 1


@dataclass(frozen=True, slots=True)
class SpeakerPlaybackResponseDto:
    success: bool
    message: str = ""
