import httpx

from application.dtos.outbound_dtos import SpeakerPlaybackRequestDto, SpeakerPlaybackResponseDto
from infrastructure.outbound.http.base import _stream_timeout  # no read timeout for long audio
from application.ports.outbound_ports import SpeakerPort
from domain.console import console_log
from domain.errors import (
    ExternalServiceTimeoutError,
    ExternalServiceUnavailableError,
)
from infrastructure.outbound.http.base import HttpServiceClient, HttpServiceConfig


class HttpSpeakerAdapter(HttpServiceClient, SpeakerPort):
    def __init__(
        self,
        config: HttpServiceConfig,
        play_stream_endpoint: str = "/process/stream/set",
        client=None,
    ) -> None:
        super().__init__(config, client)
        self._play_stream_endpoint = play_stream_endpoint

    async def play_stream(self, request: SpeakerPlaybackRequestDto) -> SpeakerPlaybackResponseDto:
        try:
            console_log(
                "speaker-adapter",
                "posting TTS audio stream to speaker playback endpoint",
                endpoint=self._play_stream_endpoint,
                sample_rate=request.sample_rate,
                channels=request.channels,
            )
            response = await self._client.post(
                self._url(self._play_stream_endpoint),
                params={
                    "sample_rate": request.sample_rate,
                    "channels": request.channels,
                },
                content=request.audio_stream,
                headers=self._headers({"Content-Type": "application/x-ndjson"}),
                timeout=_stream_timeout(self._config.timeout_seconds),
            )
            self._raise_for_expected_status(response)
            message = _response_message(response)
            console_log(
                "speaker-adapter",
                "speaker stream input accepted",
                status_code=response.status_code,
                provider_message=message,
            )
            return SpeakerPlaybackResponseDto(success=True, message=message)
        except httpx.TimeoutException as exc:
            console_log("speaker-adapter", "speaker playback timed out", error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("speaker-adapter", "speaker playback request failed", error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

def _response_message(response: httpx.Response) -> str:
    if not response.headers.get("content-type", "").startswith("application/json"):
        return "Speaker stream input accepted"
    try:
        payload = response.json()
    except ValueError:
        return "Speaker stream input accepted"
    if not isinstance(payload, dict):
        return "Speaker stream input accepted"
    message = payload.get("message")
    if isinstance(message, str) and message:
        return message
    data = payload.get("data")
    if isinstance(data, dict):
        data_message = data.get("message")
        if isinstance(data_message, str) and data_message:
            return data_message
    return "Speaker stream input accepted"
