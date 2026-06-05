from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

import asyncio
import httpx

from application.dtos.outbound_dtos import ExternalHealthResponseDto
from domain.console import console_log
from domain.errors import (
    ExternalServiceAuthenticationError,
    ExternalServiceInvalidResponseError,
    ExternalServiceTimeoutError,
    ExternalServiceUnavailableError,
)


@dataclass(frozen=True, slots=True)
class HttpServiceConfig:
    service_name: str
    base_url: str
    timeout_seconds: float = 30.0
    api_key: str = ""


class HttpServiceClient:
    def __init__(self, config: HttpServiceConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            console_log("http-client", "closing owned HTTP client", service=self._config.service_name)
            await self._client.aclose()

    async def check_health(self) -> ExternalHealthResponseDto:
        try:
            url = self._url("/health")
            console_log("http-client", "sending health request", service=self._config.service_name, method="GET", url=url)
            response = await self._client.get(url, headers=self._headers())
            console_log(
                "http-client",
                "received health response",
                service=self._config.service_name,
                status_code=response.status_code,
            )
            if response.status_code in (401, 403):
                raise ExternalServiceAuthenticationError(self._config.service_name, "authentication failed")
            return ExternalHealthResponseDto(response.status_code == 200, f"HTTP {response.status_code}")
        except httpx.TimeoutException as exc:
            console_log("http-client", "health request timed out", service=self._config.service_name, error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("http-client", "health request failed", service=self._config.service_name, error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{self._config.base_url.rstrip('/')}/{path_or_url.lstrip('/')}"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        if extra:
            headers.update(extra)
        return headers

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalServiceInvalidResponseError(
                self._config.service_name,
                "response was not valid JSON",
            ) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            console_log("http-client", "provider authentication failed", service=self._config.service_name)
            raise ExternalServiceAuthenticationError(self._config.service_name, "authentication failed")
        if response.status_code == 404:
            console_log("http-client", "provider endpoint not found", service=self._config.service_name)
            raise ExternalServiceUnavailableError(self._config.service_name, "endpoint not found")
        if response.status_code >= 400:
            console_log(
                "http-client",
                "provider returned error",
                service=self._config.service_name,
                status_code=response.status_code,
            )
            raise ExternalServiceUnavailableError(
                self._config.service_name,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

    def _raise_for_expected_status(self, response: httpx.Response, expected_status_code: int = 200) -> None:
        self._raise_for_status(response)
        if response.status_code != expected_status_code:
            console_log(
                "http-client",
                "provider returned unexpected success status",
                service=self._config.service_name,
                status_code=response.status_code,
                expected_status_code=expected_status_code,
            )
            raise ExternalServiceUnavailableError(
                self._config.service_name,
                f"expected HTTP {expected_status_code}, received HTTP {response.status_code}",
            )

    async def _bytes_from_stream(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        content: AsyncIterator[bytes] | bytes | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        full_url = self._url(url)
        console_log(
            "http-client",
            "opening byte stream",
            service=self._config.service_name,
            method=method,
            url=full_url,
        )
        chunk_count = 0
        byte_count = 0
        try:
            async with self._client.stream(
                method,
                full_url,
                params=params,
                content=content,
                json=json,
                headers=self._headers(headers),
                timeout=_stream_timeout(self._config.timeout_seconds),
            ) as response:
                console_log(
                    "http-client",
                    "byte stream response opened",
                    service=self._config.service_name,
                    status_code=response.status_code,
                )
                self._raise_for_expected_status(response)
                async for chunk in response.aiter_bytes():
                    if chunk:
                        chunk_count += 1
                        byte_count += len(chunk)
                        console_log(
                            "http-client",
                            "received byte stream chunk",
                            service=self._config.service_name,
                            chunk=chunk_count,
                            bytes=len(chunk),
                            total_bytes=byte_count,
                        )
                        yield chunk
                console_log(
                    "http-client",
                    "byte stream completed",
                    service=self._config.service_name,
                    chunks=chunk_count,
                    total_bytes=byte_count,
                )
        except asyncio.CancelledError:
            console_log(
                "http-client",
                "byte stream cancelled",
                service=self._config.service_name,
                chunks=chunk_count,
                total_bytes=byte_count,
            )
            raise
        except httpx.TimeoutException as exc:
            console_log("http-client", "byte stream timed out", service=self._config.service_name, error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("http-client", "byte stream failed", service=self._config.service_name, error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

    async def _open_bytes_from_stream(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        content: AsyncIterator[bytes] | bytes | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        full_url = self._url(url)
        console_log(
            "http-client",
            "eagerly opening byte stream",
            service=self._config.service_name,
            method=method,
            url=full_url,
        )
        try:
            request = self._client.build_request(
                method,
                full_url,
                params=params,
                content=content,
                json=json,
                headers=self._headers(headers),
                timeout=_stream_timeout(self._config.timeout_seconds),
            )
            response = await self._client.send(request, stream=True)
            console_log(
                "http-client",
                "eager byte stream response opened",
                service=self._config.service_name,
                status_code=response.status_code,
            )
            if response.status_code in (401, 403):
                await response.aclose()
                raise ExternalServiceAuthenticationError(self._config.service_name, "authentication failed")
            if response.status_code == 404:
                await response.aclose()
                raise ExternalServiceUnavailableError(self._config.service_name, "endpoint not found")
            if response.status_code >= 400:
                body = await response.aread()
                await response.aclose()
                raise ExternalServiceUnavailableError(
                    self._config.service_name,
                    f"HTTP {response.status_code}: {body[:200].decode('utf-8', errors='ignore')}",
                )
            if response.status_code != 200:
                await response.aclose()
                raise ExternalServiceUnavailableError(
                    self._config.service_name,
                    f"expected HTTP 200, received HTTP {response.status_code}",
                )
            return _OpenedHttpByteStream(self._config.service_name, response)
        except httpx.TimeoutException as exc:
            console_log("http-client", "eager byte stream timed out", service=self._config.service_name, error=str(exc))
            raise ExternalServiceTimeoutError(self._config.service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            console_log("http-client", "eager byte stream failed", service=self._config.service_name, error=str(exc))
            raise ExternalServiceUnavailableError(self._config.service_name, str(exc)) from exc

class _OpenedHttpByteStream:
    def __init__(self, service_name: str, response: httpx.Response) -> None:
        self._service_name = service_name
        self._response = response
        self._iterator = response.aiter_bytes().__aiter__()
        self._chunk_count = 0
        self._byte_count = 0
        self._closed = False

    def __aiter__(self) -> "_OpenedHttpByteStream":
        return self

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    async def __anext__(self) -> bytes:
        try:
            while True:
                chunk = await self._iterator.__anext__()
                if chunk:
                    self._chunk_count += 1
                    self._byte_count += len(chunk)
                    console_log(
                        "http-client",
                        "received eager byte stream chunk",
                        service=self._service_name,
                        chunk=self._chunk_count,
                        bytes=len(chunk),
                        total_bytes=self._byte_count,
                    )
                    return chunk
        except StopAsyncIteration:
            await self.aclose()
            raise
        except asyncio.CancelledError:
            console_log(
                "http-client",
                "eager byte stream iteration cancelled",
                service=self._service_name,
                chunks=self._chunk_count,
                total_bytes=self._byte_count,
            )
            await self.aclose()
            raise
        except httpx.TimeoutException as exc:
            await self.aclose()
            console_log("http-client", "eager byte stream timed out", service=self._service_name, error=str(exc))
            raise ExternalServiceTimeoutError(self._service_name, str(exc)) from exc
        except httpx.RequestError as exc:
            await self.aclose()
            console_log("http-client", "eager byte stream failed", service=self._service_name, error=str(exc))
            raise ExternalServiceUnavailableError(self._service_name, str(exc)) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._response.aclose()
        console_log(
            "http-client",
            "eager byte stream closed",
            blank_lines=2,
            service=self._service_name,
            chunks=self._chunk_count,
            total_bytes=self._byte_count,
        )


def _stream_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(timeout_seconds, read=None)
