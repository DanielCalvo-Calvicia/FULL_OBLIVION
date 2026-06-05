from dataclasses import dataclass
import asyncio
from typing import AsyncIterator
from application.dtos.services_dtos import PlaybackStreamResponseDto

@dataclass(slots=True, frozen=True)
class InitInboundAdapterDto:
    """Configures the inbound HTTP/WebSocket network adapter."""
    allow_origins: tuple[str, ...] = ("*",)
    autoload_stream_url: str | None = None


@dataclass(slots=True, frozen=True)
class StartSpeakerStreamRequestDto:
    """Inbound client payload delivering raw audio chunks."""
    audio_stream: AsyncIterator[bytes]
    sample_rate: int = 24000
    channels: int = 1
    setup_future: asyncio.Future[PlaybackStreamResponseDto] | None = None

@dataclass(slots=True, frozen=True)
class StartSpeakerStreamResponseDto:
    """Outcome of starting/queuing playback."""
    success: bool
    message: str
