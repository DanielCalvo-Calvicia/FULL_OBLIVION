from application.services.service import BrainService
from composition_root.config import load_config
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.microphone.microphone_adapter import HttpMicrophoneAdapter
from infrastructure.outbound.http.speaker.speaker_adapter import HttpSpeakerAdapter
from infrastructure.outbound.http.stt.stt_adapter import HttpSTTAdapter
from infrastructure.outbound.http.tts.tts_adapter import HttpTTSAdapter


class LiveMicroservices:
    def __init__(self) -> None:
        config = load_config()
        self.microphone_adapter = HttpMicrophoneAdapter(
            HttpServiceConfig(
                "microphone",
                config.microphone_base_url,
                config.provider_timeout_seconds,
                config.provider_api_key,
            ),
            stream_endpoint=config.microphone_stream_endpoint,
            start_endpoint=config.microphone_start_endpoint,
            stop_endpoint=config.microphone_stop_endpoint,
        )
        self.stt_adapter = HttpSTTAdapter(
            HttpServiceConfig("stt", config.stt_base_url, config.provider_timeout_seconds, config.provider_api_key),
            set_stream_endpoint=config.stt_set_stream_endpoint,
            get_stream_endpoint=config.stt_get_stream_endpoint,
            batch_endpoint=config.stt_batch_endpoint,
        )
        self.tts_adapter = HttpTTSAdapter(
            HttpServiceConfig("tts", config.tts_base_url, config.provider_timeout_seconds, config.provider_api_key),
            set_stream_endpoint=config.tts_set_stream_endpoint,
            get_stream_endpoint=config.tts_get_stream_endpoint,
        )
        self.speaker_adapter = HttpSpeakerAdapter(
            HttpServiceConfig(
                "speaker",
                config.speaker_base_url,
                config.provider_timeout_seconds,
                config.provider_api_key,
            ),
            play_stream_endpoint=config.speaker_play_stream_endpoint,
        )
        self.service = BrainService(
            self.microphone_adapter,
            self.stt_adapter,
            self.tts_adapter,
            self.speaker_adapter,
        )

    async def close(self) -> None:
        await self.microphone_adapter.close()
        await self.stt_adapter.close()
        await self.tts_adapter.close()
        await self.speaker_adapter.close()
