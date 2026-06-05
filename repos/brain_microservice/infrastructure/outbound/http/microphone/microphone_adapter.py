import httpx

from application.dtos.outbound_dtos import MicrophoneStreamRequestDto, MicrophoneStreamResponseDto
from application.ports.outbound_ports import MicrophonePort
from domain.console import console_log
from domain.errors import ExternalServiceTimeoutError, ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceClient, HttpServiceConfig


class HttpMicrophoneAdapter(HttpServiceClient, MicrophonePort):
    def __init__(
        self,
        config: HttpServiceConfig,
        stream_endpoint: str = "/stream",
        start_endpoint: str = "/start",
        stop_endpoint: str = "/stop",
        client=None,
    ) -> None:
        super().__init__(config, client)
        self._stream_endpoint = stream_endpoint
        self._start_endpoint = start_endpoint
        self._stop_endpoint = stop_endpoint
        self._active_stream = None

    async def get_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        console_log(
            "microphone-adapter",
            "getting microphone stream output",
            sample_rate=request.sample_rate,
            chunk_size=request.chunk_size,
        )
        params = {"sample_rate": request.sample_rate, "chunk_size": request.chunk_size}
        stream = await self._open_bytes_from_stream("GET", self._stream_endpoint, params=params)
        sample_rate = _sample_rate_from_stream_headers(stream, request.sample_rate)
        console_log("microphone-adapter", "microphone stream output is open", sample_rate=sample_rate)
        return MicrophoneStreamResponseDto(audio_stream=stream, sample_rate=sample_rate)

    async def start_stream(self, request: MicrophoneStreamRequestDto) -> MicrophoneStreamResponseDto:
        payload = {
            "sample_rate": request.sample_rate,
            "channels": 1,
            "chunk_size": request.chunk_size,
        }
        console_log(
            "microphone-adapter",
            "starting microphone stream and keeping start response open",
            endpoint=self._start_endpoint,
            sample_rate=request.sample_rate,
            chunk_size=request.chunk_size,
        )
        stream = await self._open_bytes_from_stream("POST", self._start_endpoint, json=payload)
        self._active_stream = stream
        sample_rate = _sample_rate_from_stream_headers(stream, request.sample_rate)
        console_log("microphone-adapter", "microphone start stream output is open", sample_rate=sample_rate)

        return MicrophoneStreamResponseDto(audio_stream=stream, sample_rate=sample_rate)

    async def stop_stream(self) -> None:
        try:
            console_log("microphone-adapter", "stopping microphone stream via API", endpoint=self._stop_endpoint)
            response = await self._client.post(
                self._url(self._stop_endpoint),
                json={},
                headers=self._headers(),
            )
            self._raise_for_status(response)
            console_log("microphone-adapter", "microphone stream stop accepted", status_code=response.status_code)
        except httpx.TimeoutException as exc:
            console_log("microphone-adapter", "microphone stop timed out", error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("microphone-adapter", "microphone stop request failed", error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc
        finally:
            if self._active_stream is not None:
                close = getattr(self._active_stream, "aclose", None)
                if close is not None:
                    await close()
                self._active_stream = None


def _sample_rate_from_stream_headers(stream, fallback: int) -> int:
    headers = getattr(stream, "headers", None)
    if headers is None:
        return fallback
    try:
        value = headers.get("X-Sample-Rate")
    except AttributeError:
        return fallback
    if value is None:
        return fallback
    try:
        sample_rate = int(value)
    except (TypeError, ValueError):
        return fallback
    return sample_rate if sample_rate > 0 else fallback
