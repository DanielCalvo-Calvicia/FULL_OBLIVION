from dataclasses import dataclass
from typing import AsyncIterator


# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class InitInboundAdapterDto:
    """Inbound HTTP configuration DTO."""
    pass


# ──────────────────────────────────────────────
# STREAM (Real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessStreamRequestDto:
    """Inbound request to synthesize a real-time text stream to audio."""
    text_stream: AsyncIterator[str]
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class ProcessStreamResponseDto:
    """Inbound response containing a real-time synthesized audio stream."""
    audio_stream: AsyncIterator[bytes]


# ──────────────────────────────────────────────
# DECOUPLED STREAM (Single Flow)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class SetStreamRequestDto:
    """Inbound request to set the input text stream to synthesize in the background."""
    text_stream: AsyncIterator[str]
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class GetStreamRequestDto:
    """Inbound request to retrieve the active synthesized audio stream."""
    pass


@dataclass(slots=True, frozen=True)
class GetStreamResponseDto:
    """Inbound response containing the active synthesized audio stream."""
    audio_stream: AsyncIterator[bytes]



# ──────────────────────────────────────────────
# BATCH (Non real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessBatchRequestDto:
    """Inbound request to synthesize a complete text string."""
    text: str
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class ProcessBatchResponseDto:
    """Inbound response containing the full synthesized audio buffer."""
    audio_data: bytes


# ──────────────────────────────────────────────
# AVAILABILITY
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class TTSAvailabilityRequestDto:
    pass


@dataclass(slots=True, frozen=True)
class TTSAvailabilityResponseDto:
    is_available: bool
