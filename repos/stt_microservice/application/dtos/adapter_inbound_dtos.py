from dataclasses import dataclass
from typing import AsyncIterator, Optional

from application.dtos.audio_stream_items import CompletedAudioSegment


# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class InitInboundAdapterDto:
    autoload_voice_stream_url: Optional[str] = None


# ──────────────────────────────────────────────
# STREAM (Real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessStreamRequestDto:
    """Inbound request to process a real-time audio stream."""
    audio_stream: AsyncIterator[bytes | CompletedAudioSegment]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(slots=True, frozen=True)
class ProcessStreamResponseDto:
    """Inbound response containing a real-time text stream."""
    text_stream: AsyncIterator[str]


@dataclass(slots=True, frozen=True)
class SetStreamRequestDto:
    """Inbound request to feed the shared decoupled audio stream."""
    audio_stream: AsyncIterator[bytes | CompletedAudioSegment]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(slots=True, frozen=True)
class SetStreamResponseDto:
    """Inbound response confirming the shared decoupled stream completed."""
    accepted: bool


@dataclass(slots=True, frozen=True)
class GetStreamRequestDto:
    """Inbound request to read the shared decoupled transcription stream."""
    pass


@dataclass(slots=True, frozen=True)
class GetStreamResponseDto:
    """Inbound response containing the shared decoupled text stream."""
    text_stream: AsyncIterator[str]


# ──────────────────────────────────────────────
# BATCH (Non real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessBatchRequestDto:
    """Inbound request to transcribe a complete audio buffer."""
    audio_data: bytes
    sample_rate: int = 16000


@dataclass(slots=True, frozen=True)
class ProcessBatchResponseDto:
    """Inbound response containing the full transcribed text."""
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
