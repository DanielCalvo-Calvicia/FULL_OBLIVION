from application.dtos.inbound_dtos import (
    BatchTranscriptionRequestDto,
    MicrophoneTranscriptionRequestDto,
    TextToSpeechPlaybackRequestDto,
    VoicePipelineRequestDto,
)
from application.dtos.service_dtos import (
    BatchTranscriptionServiceRequestDto,
    MicrophoneTranscriptionServiceRequestDto,
    TextToSpeechPlaybackServiceRequestDto,
    VoicePipelineServiceRequestDto,
)


def map_text_to_speech_request(
    request: TextToSpeechPlaybackRequestDto,
) -> TextToSpeechPlaybackServiceRequestDto:
    return TextToSpeechPlaybackServiceRequestDto(
        text=request.text,
        sample_rate=request.sample_rate,
        channels=request.channels,
    )


def map_batch_transcription_request(
    request: BatchTranscriptionRequestDto,
) -> BatchTranscriptionServiceRequestDto:
    return BatchTranscriptionServiceRequestDto(
        audio_data=request.audio_data,
        sample_rate=request.sample_rate,
    )


def map_microphone_transcription_request(
    request: MicrophoneTranscriptionRequestDto,
) -> MicrophoneTranscriptionServiceRequestDto:
    return MicrophoneTranscriptionServiceRequestDto(
        sample_rate=request.sample_rate,
        chunk_size=request.chunk_size,
        silence_threshold=request.silence_threshold,
        silence_limit_seconds=request.silence_limit_seconds,
        max_segments=request.max_segments,
    )


def map_voice_pipeline_request(request: VoicePipelineRequestDto) -> VoicePipelineServiceRequestDto:
    return VoicePipelineServiceRequestDto(
        microphone_sample_rate=request.microphone_sample_rate,
        microphone_chunk_size=request.microphone_chunk_size,
        stt_silence_threshold=request.stt_silence_threshold,
        stt_silence_limit_seconds=request.stt_silence_limit_seconds,
        max_text_segments=request.max_text_segments,
        tts_sample_rate=request.tts_sample_rate,
        speaker_channels=request.speaker_channels,
    )
