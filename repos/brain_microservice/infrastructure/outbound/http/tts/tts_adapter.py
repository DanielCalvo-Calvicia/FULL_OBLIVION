import httpx

from application.dtos.outbound_dtos import (
    ExternalHealthResponseDto,
    TTSAudioStreamRequestDto,
    TTSAudioStreamResponseDto,
    TTSSetStreamRequestDto,
    TTSTextStreamRequestDto,
)
from application.ports.outbound_ports import TTSPort
from domain.console import console_log
from domain.errors import ExternalServiceTimeoutError, ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceClient, HttpServiceConfig


class HttpTTSAdapter(HttpServiceClient, TTSPort):
    def __init__(
        self,
        config: HttpServiceConfig,
        set_stream_endpoint: str = "/process/stream/set",
        get_stream_endpoint: str = "/process/stream/get",
        client=None,
    ) -> None:
        super().__init__(config, client)
        self._set_stream_endpoint = set_stream_endpoint
        self._get_stream_endpoint = get_stream_endpoint

    async def check_health(self) -> ExternalHealthResponseDto:
        try:
            console_log("tts-adapter", "checking TTS availability")
            response = await self._client.get(self._url("/available"), headers=self._headers())
            self._raise_for_expected_status(response)
            payload = self._json(response)
            data = payload.get("data", False)
            is_available = bool(data.get("is_available", data) if isinstance(data, dict) else data)
            console_log("tts-adapter", "TTS availability response received", available=is_available)
            return ExternalHealthResponseDto(is_available, f"HTTP {response.status_code}")
        except ExternalServiceUnavailableError:
            return await super().check_health()
        except httpx.TimeoutException as exc:
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

    async def set_stream(self, request: TTSSetStreamRequestDto) -> None:
        console_log("tts-adapter", "sending text to TTS stream input", chars=len(request.text))
        await self._post_text_stream(
            _single_text_bytes(request.text),
            sample_rate=request.sample_rate,
            channels=request.channels,
        )

    async def set_text_stream(self, request: TTSTextStreamRequestDto) -> None:
        console_log("tts-adapter", "connecting text stream to TTS stream input")
        await self._post_text_stream(
            request.text_stream,
            sample_rate=request.sample_rate,
            channels=request.channels,
        )

    async def get_stream(self, request: TTSAudioStreamRequestDto) -> TTSAudioStreamResponseDto:
        console_log(
            "tts-adapter",
            "getting TTS audio stream output",
            sample_rate=request.sample_rate,
            channels=request.channels,
        )
        stream = await self._open_bytes_from_stream(
            "GET",
            self._get_stream_endpoint,
            params={
                "sample_rate": request.sample_rate,
                "channels": request.channels,
                "keep_open_after_completed": request.keep_open_after_completed,
            },
        )
        console_log("tts-adapter", "TTS audio stream output is open", level="warn")
        return TTSAudioStreamResponseDto(
            audio_stream=stream
        )

    async def _post_text_stream(self, text_stream, *, sample_rate: int, channels: int) -> None:
        try:
            console_log(
                "tts-adapter",
                "posting text stream to TTS",
                endpoint=self._set_stream_endpoint,
                sample_rate=sample_rate,
                channels=channels,
            )
            response = await self._client.post(
                self._url(self._set_stream_endpoint),
                params={"sample_rate": sample_rate, "channels": channels},
                content=text_stream,
                headers=self._headers({"Content-Type": "application/x-ndjson"}),
            )
            self._raise_for_status(response)
            if response.status_code not in (200, 202):
                raise ExternalServiceUnavailableError(
                    self._config.service_name,
                    f"expected HTTP 200 or 202, received HTTP {response.status_code}",
                )
            console_log("tts-adapter", "TTS stream input accepted", status_code=response.status_code)
        except httpx.TimeoutException as exc:
            console_log("tts-adapter", "TTS stream input timed out", error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("tts-adapter", "TTS stream input request failed", error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

async def _single_text_bytes(text: str):
    if text:
        yield text.encode("utf-8")
