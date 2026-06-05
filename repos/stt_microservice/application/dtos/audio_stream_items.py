from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class CompletedAudioSegment:
    audio_data: bytes
    source_sequence: Any = None

