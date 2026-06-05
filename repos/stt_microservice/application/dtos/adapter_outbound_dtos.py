from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(slots=True, frozen=True)
class InitOutboundAdapterDto:
    """Configuration for initializing the outbound STT adapter."""
    api_key: str = ""
    model_name: str = "whisper-1"
    language: str = "en"


# ──────────────────────────────────────────────
# STREAM (Real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessStreamRequestDto:
    """Request to process a real-time audio stream."""
    audio_stream: AsyncIterator[bytes]
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0


@dataclass(slots=True, frozen=True)
class ProcessStreamResponseDto:
    """Response containing a real-time text stream."""
    text_stream: AsyncIterator[str]


# ──────────────────────────────────────────────
# BATCH (Non real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessBatchRequestDto:
    """Request to transcribe a complete audio buffer (non real-time)."""
    audio_data: bytes
    sample_rate: int = 16000


@dataclass(slots=True, frozen=True)
class ProcessBatchResponseDto:
    """Response containing the full transcribed text."""
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
