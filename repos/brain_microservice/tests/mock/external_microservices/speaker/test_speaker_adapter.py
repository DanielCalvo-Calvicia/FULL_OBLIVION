import json

import httpx
import pytest

from application.dtos.outbound_dtos import SpeakerPlaybackRequestDto
from domain.errors import ExternalServiceUnavailableError
from infrastructure.outbound.http.base import HttpServiceConfig
from infrastructure.outbound.http.speaker.speaker_adapter import HttpSpeakerAdapter
from application.services.steps.stream_internal.external_events import stream_event_bytes
from tests.shared.streams import byte_stream


def _ndjson_events(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def _assert_standard_event(event: dict, event_type: str, sequence: int) -> None:
    assert event["type"] == event_type
    assert event["sequence"] == sequence
    assert event["timestamp"].endswith("Z")
    assert isinstance(event["payload"], dict)


@pytest.mark.asyncio
async def test_speaker_adapter_posts_audio_stream_to_set_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/process/stream/set"
        assert request.url.params["sample_rate"] == "24000"
        assert request.url.params["channels"] == "1"
        assert request.headers["content-type"] == "application/x-ndjson"
        events = _ndjson_events(await request.aread())
        assert len(events) == 3
        _assert_standard_event(events[0], "stream_started", 1)
        _assert_standard_event(events[1], "partial", 2)
        assert events[1]["payload"] == {"bytes_base64": "YXVkaW8="}
        _assert_standard_event(events[2], "completed", 3)
        assert events[2]["payload"] == {"reason": "completed", "output_bytes_base64": "YXVkaW8="}
        return httpx.Response(
            200,
            json={
                "action": "set_stream_http",
                "status": "success",
                "status_code": 200,
                "message": "Playback stream accepted",
                "data": None,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSpeakerAdapter(
        HttpServiceConfig("speaker", "http://speaker.test"),
        client=client,
    )

    body = b"".join(
        [
            stream_event_bytes("stream_started", 1, {}),
            stream_event_bytes("partial", 2, {"bytes_base64": "YXVkaW8="}),
            stream_event_bytes("completed", 3, {"reason": "completed", "output_bytes_base64": "YXVkaW8="}),
        ]
    )
    response = await adapter.play_stream(SpeakerPlaybackRequestDto(audio_stream=byte_stream((body,)), sample_rate=24000, channels=1))

    assert response.success is True
    assert response.message == "Playback stream accepted"
    await client.aclose()


@pytest.mark.asyncio
async def test_speaker_adapter_accepts_empty_success_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/set"
        events = _ndjson_events(await request.aread())
        assert events[0]["payload"] == {"bytes_base64": "YXVkaW8="}
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSpeakerAdapter(
        HttpServiceConfig("speaker", "http://speaker.test"),
        client=client,
    )

    body = stream_event_bytes("partial", 1, {"bytes_base64": "YXVkaW8="})
    response = await adapter.play_stream(SpeakerPlaybackRequestDto(audio_stream=byte_stream((body,)), sample_rate=24000, channels=1))

    assert response.success is True
    assert response.message == "Speaker stream input accepted"
    await client.aclose()


@pytest.mark.asyncio
async def test_speaker_adapter_surfaces_set_endpoint_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/process/stream/set"
        events = _ndjson_events(await request.aread())
        assert events[0]["payload"] == {"bytes_base64": "YmFkLWF1ZGlv"}
        return httpx.Response(
            500,
            json={
                "action": "set_stream_http",
                "status": "error",
                "status_code": 500,
                "message": "Hardware stream open failure",
                "data": None,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpSpeakerAdapter(
        HttpServiceConfig("speaker", "http://speaker.test"),
        client=client,
    )

    with pytest.raises(ExternalServiceUnavailableError, match="HTTP 500"):
        body = stream_event_bytes("partial", 1, {"bytes_base64": "YmFkLWF1ZGlv"})
        await adapter.play_stream(
            SpeakerPlaybackRequestDto(audio_stream=byte_stream((body,)), sample_rate=24000, channels=1)
        )

    await client.aclose()
