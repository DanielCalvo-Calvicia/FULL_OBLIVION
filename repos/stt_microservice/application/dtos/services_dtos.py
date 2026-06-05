from dataclasses import dataclass
from typing import AsyncIterator

from application.dtos.audio_stream_items import CompletedAudioSegment


# ──────────────────────────────────────────────
# STREAM (Real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessStreamRequestDto:
    """Service-layer request for real-time stream processing."""
    audio_stream: AsyncIterator[bytes | CompletedAudioSegment]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(slots=True, frozen=True)
class ProcessStreamResponseDto:
    """Service-layer response containing a real-time text stream."""
    text_stream: AsyncIterator[str]


@dataclass(slots=True, frozen=True)
class SetStreamRequestDto:
    """Service-layer request to feed the shared decoupled audio stream."""
    audio_stream: AsyncIterator[bytes | CompletedAudioSegment]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(slots=True, frozen=True)
class SetStreamResponseDto:
    """Service-layer response confirming the shared decoupled stream completed."""
    accepted: bool


@dataclass(slots=True, frozen=True)
class GetStreamRequestDto:
    """Service-layer request to read the shared decoupled text stream."""
    pass


@dataclass(slots=True, frozen=True)
class GetStreamResponseDto:
    """Service-layer response containing a shared decoupled text stream."""
    text_stream: AsyncIterator[str]


# ──────────────────────────────────────────────
# BATCH (Non real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessBatchRequestDto:
    """Service-layer request to transcribe a complete audio buffer."""
    audio_data: bytes
    sample_rate: int = 16000


@dataclass(slots=True, frozen=True)
class ProcessBatchResponseDto:
    """Service-layer response containing the full transcribed text."""
    text: str


# ──────────────────────────────────────────────
# AVAILABILITY
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class STTAvailabilityRequestDto:
    pass


@dataclass(slots=True, frozen=True)
class STTAvailabilityResponseDto:
    is_available: bool
