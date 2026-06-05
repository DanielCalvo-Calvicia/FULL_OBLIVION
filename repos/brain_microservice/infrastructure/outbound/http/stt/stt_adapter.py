import httpx

from application.dtos.outbound_dtos import (
    ExternalHealthResponseDto,
    STTBatchRequestDto,
    STTBatchResponseDto,
    STTSetStreamRequestDto,
    STTStreamResponseDto,
    STTTextStreamRequestDto,
)
from application.ports.outbound_ports import STTPort
from domain.console import console_log
from domain.errors import ExternalServiceTimeoutError, ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceClient, HttpServiceConfig


class HttpSTTAdapter(HttpServiceClient, STTPort):
    def __init__(
        self,
        config: HttpServiceConfig,
        set_stream_endpoint: str = "/process/stream/set",
        get_stream_endpoint: str = "/process/stream/get",
        batch_endpoint: str = "/process/batch",
        client=None,
    ) -> None:
        super().__init__(config, client)
        self._set_stream_endpoint = set_stream_endpoint
        self._get_stream_endpoint = get_stream_endpoint
        self._batch_endpoint = batch_endpoint

    async def check_health(self) -> ExternalHealthResponseDto:
        try:
            console_log("stt-adapter", "checking STT availability")
            response = await self._client.get(self._url("/available"), headers=self._headers())
            self._raise_for_expected_status(response)
            payload = self._json(response)
            data = payload.get("data", False)
            is_available = bool(data.get("is_available", data) if isinstance(data, dict) else data)
            console_log("stt-adapter", "STT availability response received", available=is_available)
            return ExternalHealthResponseDto(is_available, f"HTTP {response.status_code}")
        except ExternalServiceUnavailableError:
            return await super().check_health()
        except httpx.TimeoutException as exc:
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

    async def set_stream(self, request: STTSetStreamRequestDto) -> None:
        console_log(
            "stt-adapter",
            "posting STT stream input",
            sample_rate=request.sample_rate,
            chunk_size=request.chunk_size,
            silence_threshold=request.silence_threshold,
            silence_limit_seconds=request.silence_limit_seconds,
        )
        params = {
            "sample_rate": request.sample_rate,
            "chunk_size": request.chunk_size,
            "silence_threshold": request.silence_threshold,
            "silence_limit_seconds": request.silence_limit_seconds,
        }
        try:
            response = await self._client.post(
                self._url(self._set_stream_endpoint),
                params=params,
                content=request.audio_stream,
                headers=self._headers({"Content-Type": "application/x-ndjson"}),
            )
            self._raise_for_expected_status(response)
            console_log("stt-adapter", "STT stream input accepted", status_code=response.status_code)
        except httpx.TimeoutException as exc:
            console_log("stt-adapter", "STT stream input timed out", error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("stt-adapter", "STT stream input request failed", error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

    async def get_stream(self, request: STTTextStreamRequestDto) -> STTStreamResponseDto:
        console_log(
            "stt-adapter",
            "getting STT text stream output",
            sample_rate=request.sample_rate,
            chunk_size=request.chunk_size,
            silence_threshold=request.silence_threshold,
            silence_limit_seconds=request.silence_limit_seconds,
        )
        params = {
            "sample_rate": request.sample_rate,
            "chunk_size": request.chunk_size,
            "silence_threshold": request.silence_threshold,
            "silence_limit_seconds": request.silence_limit_seconds,
        }
        byte_stream = await self._open_bytes_from_stream("GET", self._get_stream_endpoint, params=params)
        console_log("stt-adapter", "STT text stream output is open")
        return STTStreamResponseDto(text_stream=byte_stream)

    async def process_batch(self, request: STTBatchRequestDto) -> STTBatchResponseDto:
        try:
            console_log(
                "stt-adapter",
                "sending batch audio to STT",
                bytes=len(request.audio_data),
                sample_rate=request.sample_rate,
            )
            response = await self._client.post(
                self._url(self._batch_endpoint),
                params={"sample_rate": request.sample_rate},
                content=request.audio_data,
                headers=self._headers({"Content-Type": "application/octet-stream"}),
            )
            self._raise_for_expected_status(response)
            console_log("stt-adapter", "batch STT response received", status_code=response.status_code)
        except httpx.TimeoutException as exc:
            console_log("stt-adapter", "batch STT timed out", error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("stt-adapter", "batch STT request failed", error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

        payload = self._json(response)
        data = payload.get("data", payload)
        if isinstance(data, dict):
            text = data.get("text", "")
        else:
            text = str(data or "")
        console_log("stt-adapter", "batch STT text parsed", chars=len(text))
        return STTBatchResponseDto(text=text)
