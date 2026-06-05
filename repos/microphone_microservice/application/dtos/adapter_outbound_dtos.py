from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass(slots=True, frozen=True)
class InitOutboundAdapterDto:
    default_fallback_rate: int = 16000
    target_keywords: list[str] = field(default_factory=list)

@dataclass(slots=True, frozen=True)
class StartMicrophoneStreamRequestDto:
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024


@dataclass(slots=True, frozen=True)
class StartMicrophoneStreamResponseDto:
    stream: AsyncIterator[bytes]
    sample_rate: int


@dataclass(slots=True, frozen=True)
class StopMicrophoneStreamRequestDto:
    pass

@dataclass(slots=True, frozen=True)
class StopMicrophoneStreamResponseDto:
    success: bool = True


@dataclass(slots=True, frozen=True)
class MicrophoneAvailabilityRequestDto:
    pass

@dataclass(slots=True, frozen=True)
class MicrophoneAvailabilityResponseDto:
    is_available: bool
