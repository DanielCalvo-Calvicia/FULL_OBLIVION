from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass(slots=True, frozen=True)
class InitOutboundAdapterDto:
    """Configuration for initializing the outbound TTS adapter."""
    speech_rate: int = 140
    voice_name_preference: str = "Zira"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini-tts"
    openai_voice: str = "alloy"
    openai_response_format: str = "wav"
    openai_instructions: Optional[str] = None
    openai_speed: Optional[float] = None
    openai_base_url: str = "https://api.openai.com/v1"


# ──────────────────────────────────────────────
# STREAM (Real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessStreamRequestDto:
    """Request to synthesize a real-time text stream to audio."""
    text_stream: AsyncIterator[str]
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class ProcessStreamResponseDto:
    """Response containing a real-time synthesized audio stream."""
    audio_stream: AsyncIterator[bytes]


# ──────────────────────────────────────────────
# DECOUPLED STREAM (Single Flow)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class SetStreamRequestDto:
    """Request to set the input text stream for background synthesis."""
    text_stream: AsyncIterator[str]
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class GetStreamRequestDto:
    """Request to retrieve the active synthesized audio stream."""
    pass


@dataclass(slots=True, frozen=True)
class GetStreamResponseDto:
    """Response containing the active synthesized audio stream."""
    audio_stream: AsyncIterator[bytes]



# ──────────────────────────────────────────────
# BATCH (Non real-time)
# ──────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class ProcessBatchRequestDto:
    """Request to synthesize a complete text string (non real-time)."""
    text: str
    sample_rate: int = 22050
    channels: int = 1


@dataclass(slots=True, frozen=True)
class ProcessBatchResponseDto:
    """Response containing the full synthesized audio buffer."""
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
