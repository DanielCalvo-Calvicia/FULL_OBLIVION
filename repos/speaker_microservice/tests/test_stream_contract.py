import asyncio
import base64
import json
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto
from application.dtos.services_dtos import (
    PlaybackStreamRequestDto,
    PlaybackStreamResponseDto,
    SpeakerCleanupResponseDto,
)
from application.ports.service_port import SpeakerServicePort
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter


class FakeSpeakerService(SpeakerServicePort):
    def __init__(self, success: bool = True, message: str = "ok"):
        self.success = success
        self.message = message
        self.received_chunks: list[bytes] = []

    async def play(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
        setup_response = PlaybackStreamResponseDto(success=self.success, message=self.message)
        if request.setup_future is not None and not request.setup_future.done():
            request.setup_future.set_result(setup_response)
        if not self.success:
            return setup_response
        try:
            async for chunk in request.audio_stream:
                if chunk:
                    self.received_chunks.append(chunk)
        except Exception as e:
            return PlaybackStreamResponseDto(success=False, message=str(e))
        return setup_response

    async def stop_and_cleanup(self) -> SpeakerCleanupResponseDto:
        return SpeakerCleanupResponseDto(success=True)


def build_app(service: FakeSpeakerService) -> FastAPI:
    app = FastAPI()
    FastApiAdapter(service_port=service, app=app, config=InitInboundAdapterDto())
    return app


def build_client(service: FakeSpeakerService) -> TestClient:
    app = build_app(service)
    return TestClient(app)


def parse_events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def assert_event_shape(event: dict) -> None:
    assert set(event) == {"type", "sequence", "timestamp", "payload"}
    assert isinstance(event["type"], str)
    assert isinstance(event["sequence"], int)
    assert isinstance(event["payload"], dict)
    assert event["timestamp"].endswith("Z")
    datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))


def ndjson_event(event_type: str, sequence: int, payload: dict) -> dict:
    return {
        "type": event_type,
        "sequence": sequence,
        "timestamp": f"2026-05-30T00:00:0{sequence}.000000Z",
        "payload": payload,
    }


def ndjson_body(*events: dict) -> bytes:
    return "".join(json.dumps(event) + "\n" for event in events).encode("utf-8")


def post_ndjson(client: TestClient, body: bytes):
    return client.post(
        "/process/stream/set",
        content=body,
        headers={"content-type": "application/x-ndjson"},
    )


def find_error_message(events: list[dict]) -> str:
    errors = [event for event in events if event["type"] == "error"]
    assert errors
    return errors[0]["payload"]["message"]


def test_stream_starts_with_stream_started():
    client = build_client(FakeSpeakerService())

    response = client.post("/process/stream/set", content=b"abc")

    events = parse_events(response)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "content-length" not in response.headers
    assert events[0]["type"] == "stream_started"
    assert events[0]["payload"] == {"message": "ok"}
    for event in events:
        assert_event_shape(event)


def test_inbound_adapter_exposes_only_required_business_routes():
    app = build_app(FakeSpeakerService())
    client = TestClient(app)

    all_route_paths = {path for route in app.routes if isinstance(path := getattr(route, "path", None), str)}
    route_paths = {
        path
        for route in app.routes
        if isinstance(path := getattr(route, "path", None), str)
        if getattr(route, "tags", None) in (["Health"], ["Playback"])
    }

    assert route_paths == {"/health", "/process/stream/set"}
    assert "/play/stream" not in all_route_paths
    assert "/play/ws" not in all_route_paths
    assert client.get("/health").status_code == 200


def test_audio_body_is_consumed_without_mirroring_binary_partials():
    service = FakeSpeakerService()
    client = build_client(service)

    response = client.post("/process/stream/set", content=b"abc")

    events = parse_events(response)
    assert "partial" not in [event["type"] for event in events]
    assert service.received_chunks == [b"abc"]


def test_ndjson_stream_started_only_is_accepted_without_audio():
    service = FakeSpeakerService(message="played")
    client = build_client(service)

    response = post_ndjson(client, ndjson_body(ndjson_event("stream_started", 1, {})))

    events = parse_events(response)
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["stream_started", "completed"]
    assert service.received_chunks == []


def test_ndjson_partial_bytes_base64_is_decoded_to_audio_bytes():
    service = FakeSpeakerService()
    client = build_client(service)
    audio = b"\x01\x02pcm"

    response = post_ndjson(
        client,
        ndjson_body(
            ndjson_event("stream_started", 1, {}),
            ndjson_event("partial", 2, {"bytes_base64": base64.b64encode(audio).decode("ascii")}),
        ),
    )

    events = parse_events(response)
    assert response.status_code == 200
    assert "error" not in [event["type"] for event in events]
    assert service.received_chunks == [audio]


def test_ndjson_partial_is_consumed_before_request_body_closes():
    async def run_probe() -> None:
        class StreamingProbeService(FakeSpeakerService):
            def __init__(self) -> None:
                super().__init__(message="probe playback ok")
                self.first_chunk_seen = asyncio.Event()

            async def play(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
                setup_response = PlaybackStreamResponseDto(success=True, message="probe setup ok")
                if request.setup_future is not None and not request.setup_future.done():
                    request.setup_future.set_result(setup_response)
                try:
                    async for chunk in request.audio_stream:
                        if chunk:
                            self.received_chunks.append(chunk)
                            self.first_chunk_seen.set()
                except Exception as e:
                    return PlaybackStreamResponseDto(success=False, message=str(e))
                return PlaybackStreamResponseDto(success=True, message="probe playback ok")

        service = StreamingProbeService()
        app = build_app(service)
        audio = b"pcm-before-close"

        async def body():
            yield ndjson_body(ndjson_event("stream_started", 1, {}))
            yield ndjson_body(
                ndjson_event("partial", 2, {"bytes_base64": base64.b64encode(audio).decode("ascii")})
            )
            await asyncio.wait_for(service.first_chunk_seen.wait(), timeout=2.0)
            yield ndjson_body(ndjson_event("completed", 3, {"reason": "completed"}))

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client:
            response = await client.post(
                "/process/stream/set?sample_rate=24000&channels=1",
                content=body(),
                headers={"content-type": "application/x-ndjson"},
            )

        events = parse_events(response)
        assert response.status_code == 200
        assert [event["type"] for event in events] == ["stream_started", "completed"]
        assert service.received_chunks == [audio]

    asyncio.run(run_probe())


def test_ndjson_idle_disconnect_finalizes_without_error():
    async def run_probe() -> None:
        service = FakeSpeakerService(message="idle ok")
        app = build_app(service)
        receive_messages = [
            {"type": "http.request", "body": b"", "more_body": True},
            {"type": "http.disconnect"},
        ]
        sent_messages = []

        async def receive():
            if receive_messages:
                return receive_messages.pop(0)
            return {"type": "http.disconnect"}

        async def send(message):
            sent_messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/process/stream/set",
                "raw_path": b"/process/stream/set",
                "query_string": b"sample_rate=24000&channels=1",
                "headers": [(b"content-type", b"application/x-ndjson")],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8003),
            },
            receive,
            send,
        )

        body = b"".join(message.get("body", b"") for message in sent_messages if message["type"] == "http.response.body")
        events = [json.loads(line) for line in body.decode("utf-8").splitlines() if line]

        assert sent_messages[0]["status"] == 200
        assert [event["type"] for event in events] == ["stream_started", "completed"]
        assert events[-1]["payload"]["chunk_count"] == 0
        assert events[-1]["payload"]["byte_count"] == 0

    asyncio.run(run_probe())


def test_ndjson_completed_does_not_end_request_or_play_output_bytes():
    service = FakeSpeakerService()
    client = build_client(service)
    first_audio = b"first"
    second_audio = b"second"

    response = post_ndjson(
        client,
        ndjson_body(
            ndjson_event("stream_started", 1, {}),
            ndjson_event("partial", 2, {"bytes_base64": base64.b64encode(first_audio).decode("ascii")}),
            ndjson_event(
                "completed",
                3,
                {
                    "reason": "completed",
                    "output_bytes_base64": base64.b64encode(b"do-not-play").decode("ascii"),
                },
            ),
            ndjson_event("partial", 4, {"bytes_base64": base64.b64encode(second_audio).decode("ascii")}),
            ndjson_event("completed", 5, {"reason": "completed"}),
        ),
    )

    events = parse_events(response)
    response_completed = [event for event in events if event["type"] == "completed"]
    assert response.status_code == 200
    assert len(response_completed) == 1
    assert response_completed[0]["payload"]["reason"] == "end_of_input"
    assert service.received_chunks == [first_audio, second_audio]


def test_ndjson_rejects_bad_sequence_with_error_event():
    client = build_client(FakeSpeakerService())

    response = post_ndjson(client, ndjson_body(ndjson_event("stream_started", 2, {})))

    events = parse_events(response)
    assert response.status_code == 200
    assert "sequence must be 1" in find_error_message(events)


def test_ndjson_rejects_audio_events_before_stream_started():
    client = build_client(FakeSpeakerService())

    response = post_ndjson(
        client,
        ndjson_body(ndjson_event("partial", 1, {"bytes_base64": base64.b64encode(b"audio").decode("ascii")})),
    )

    events = parse_events(response)
    assert response.status_code == 200
    assert "stream_started event must be sent before audio events" in find_error_message(events)


def test_ndjson_rejects_malformed_json_with_error_event():
    client = build_client(FakeSpeakerService())

    response = post_ndjson(client, b'{"type":"stream_started"\n')

    events = parse_events(response)
    assert response.status_code == 200
    assert "Malformed NDJSON event" in find_error_message(events)


def test_ndjson_rejects_partial_missing_bytes_base64_with_error_event():
    client = build_client(FakeSpeakerService())

    response = post_ndjson(
        client,
        ndjson_body(
            ndjson_event("stream_started", 1, {}),
            ndjson_event("partial", 2, {}),
        ),
    )

    events = parse_events(response)
    assert response.status_code == 200
    assert "payload.bytes_base64" in find_error_message(events)


def test_ndjson_rejects_invalid_base64_with_error_event():
    client = build_client(FakeSpeakerService())

    response = post_ndjson(
        client,
        ndjson_body(
            ndjson_event("stream_started", 1, {}),
            ndjson_event("partial", 2, {"bytes_base64": "not-base64!"}),
        ),
    )

    events = parse_events(response)
    assert response.status_code == 200
    assert "not valid base64" in find_error_message(events)


def test_completed_event_is_emitted_for_each_logical_output():
    client = build_client(FakeSpeakerService(message="played"))

    response = client.post("/process/stream/set", content=b"abc")

    events = parse_events(response)
    completed = [event for event in events if event["type"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["payload"] == {
        "reason": "end_of_input",
        "output": "",
        "chunk_count": 1,
        "byte_count": 3,
        "message": "played",
    }


def test_stream_can_remain_open_after_completed():
    client = build_client(FakeSpeakerService())

    response = client.post(
        "/process/stream/set?keep_open_after_completed=true&heartbeat_interval_seconds=0.1&max_heartbeats_after_completed=1",
        content=b"abc",
    )

    events = parse_events(response)
    event_types = [event["type"] for event in events]
    completed_index = event_types.index("completed")
    heartbeat_index = event_types.index("heartbeat")
    assert completed_index < heartbeat_index
    assert events[heartbeat_index]["payload"] == {}


def test_setup_failure_returns_http_error_response():
    client = build_client(FakeSpeakerService(success=False, message="hardware unavailable"))

    response = client.post("/process/stream/set", content=b"abc")

    assert response.status_code == 500
    assert response.json()["message"] == "hardware unavailable"


def test_sequence_numbers_are_monotonic():
    client = build_client(FakeSpeakerService())

    response = client.post(
        "/process/stream/set?keep_open_after_completed=true&heartbeat_interval_seconds=0.1&max_heartbeats_after_completed=1",
        content=b"abc",
    )

    events = parse_events(response)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
