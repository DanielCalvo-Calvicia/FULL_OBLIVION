from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextToSpeechPlaybackRequestDto:
    text: str
    sample_rate: int = 24000
    channels: int = 1


@dataclass(frozen=True, slots=True)
class BatchTranscriptionRequestDto:
    audio_data: bytes
    sample_rate: int = 16000


@dataclass(frozen=True, slots=True)
class MicrophoneTranscriptionRequestDto:
    sample_rate: int = 16000
    chunk_size: int = 1024
    silence_threshold: int = 150
    silence_limit_seconds: float = 2.0
    max_segments: int = 1


@dataclass(frozen=True, slots=True)
class VoicePipelineRequestDto:
    microphone_sample_rate: int = 16000
    microphone_chunk_size: int = 1024
    stt_silence_threshold: int = 150
    stt_silence_limit_seconds: float = 2.0
    max_text_segments: int = 0
    tts_sample_rate: int = 24000
    speaker_channels: int = 1
