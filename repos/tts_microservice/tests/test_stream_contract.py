import asyncio
import base64
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from application.dtos.adapter_inbound_dtos import InitInboundAdapterDto
from application.dtos.services_dtos import (
    GetStreamResponseDto,
    GetStreamRequestDto,
    InitServiceDto,
    ProcessBatchResponseDto,
    ProcessBatchRequestDto,
    ProcessStreamResponseDto,
    ProcessStreamRequestDto,
    TTSAvailabilityResponseDto,
    TTSAvailabilityRequestDto,
    SetStreamRequestDto,
)
from application.ports.service_port import ServicePort
from application.dtos.stream_items import AudioSegmentEnd, AudioStreamError
from infrastructure.inbound.http.fastapi_adapter import FastApiAdapter, _audio_event_stream


async def _audio_chunks(*chunks: bytes):
    for chunk in chunks:
        yield chunk


async def _audio_items(*items):
    for item in items:
        yield item


async def _failing_audio_chunks():
    yield b"first"
    raise RuntimeError("synthesis failed")


def _events_from_body(body: bytes) -> list[dict]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def _events_from_sse(body: bytes) -> list[dict]:
    events = []
    for block in body.decode("utf-8").split("\n\n"):
        data_lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("".join(data_lines)))
    return events


def _events_from_response(response: httpx.Response) -> list[dict]:
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        return _events_from_sse(response.content)
    return _events_from_body(response.content)


def _text_stream_body(*chunks: str) -> bytes:
    events = [
        {
            "type": "stream_started",
            "sequence": 1,
            "timestamp": "2026-05-24T12:00:00Z",
            "payload": {},
        }
    ]
    for sequence, chunk in enumerate(chunks, start=2):
        events.append(
            {
                "type": "partial",
                "sequence": sequence,
                "timestamp": "2026-05-24T12:00:00Z",
                "payload": {"text": chunk},
            }
        )
    events.append(
        {
            "type": "completed",
            "sequence": len(events) + 1,
            "timestamp": "2026-05-24T12:00:00Z",
            "payload": {"reason": "completed", "output": "".join(chunks)},
        }
    )
    return "\n".join(json.dumps(event) for event in events).encode("utf-8")


def _assert_event_shape(test_case: unittest.TestCase, event: dict, expected_type: str, expected_sequence: int) -> None:
    test_case.assertEqual(event["type"], expected_type)
    test_case.assertEqual(event["sequence"], expected_sequence)
    test_case.assertTrue(event["timestamp"].endswith("Z"))
    test_case.assertIsInstance(event["payload"], dict)


class FakeService(ServicePort):
    async def init(self, request: InitServiceDto) -> None:
        return None

    async def process_stream(self, request: ProcessStreamRequestDto) -> ProcessStreamResponseDto:
        return ProcessStreamResponseDto(audio_stream=_audio_chunks(b"hello ", b"world"))

    async def set_stream(self, request: SetStreamRequestDto) -> None:
        return None

    async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
        return GetStreamResponseDto(
            audio_stream=_audio_items(
                b"queued ",
                b"audio",
                AudioSegmentEnd(),
                b"again",
                AudioSegmentEnd(),
            )
        )

    async def process_batch(self, request: ProcessBatchRequestDto) -> ProcessBatchResponseDto:
        return ProcessBatchResponseDto(audio_data=b"batch")

    async def is_available(self, request: TTSAvailabilityRequestDto) -> TTSAvailabilityResponseDto:
        return TTSAvailabilityResponseDto(is_available=True)


class StreamContractTests(unittest.TestCase):
    def test_process_stream_endpoint_emits_ndjson_event_contract(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/process/stream",
                    content=_text_stream_body("hello"),
                    headers={
                        "Content-Type": "application/x-ndjson",
                        "Accept": "application/x-ndjson",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))

            events = _events_from_response(response)
            self.assertEqual(
                [event["type"] for event in events],
                ["stream_started", "partial", "partial", "completed"],
            )

            for index, event in enumerate(events, start=1):
                _assert_event_shape(self, event, event["type"], index)

            self.assertEqual(events[1]["payload"].keys(), {"bytes_base64", "byte_count", "chunk_index"})
            self.assertEqual(events[2]["payload"].keys(), {"bytes_base64", "byte_count", "chunk_index"})
            self.assertEqual(
                events[3]["payload"].keys(),
                {"reason", "output_bytes_base64", "total_bytes", "chunk_count"},
            )
            self.assertEqual(base64.b64decode(events[1]["payload"]["bytes_base64"]), b"hello ")
            self.assertEqual(base64.b64decode(events[2]["payload"]["bytes_base64"]), b"world")
            self.assertEqual(events[1]["payload"]["byte_count"], 6)
            self.assertEqual(events[1]["payload"]["chunk_index"], 1)
            self.assertEqual(events[2]["payload"]["byte_count"], 5)
            self.assertEqual(events[2]["payload"]["chunk_index"], 2)
            self.assertEqual(events[3]["payload"]["reason"], "completed")
            self.assertEqual(base64.b64decode(events[3]["payload"]["output_bytes_base64"]), b"hello world")
            self.assertEqual(events[3]["payload"]["total_bytes"], 11)
            self.assertEqual(events[3]["payload"]["chunk_count"], 2)

        asyncio.run(run())

    def test_process_stream_endpoint_rejects_legacy_raw_text_input(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/process/stream", content="hello")

            self.assertEqual(response.status_code, 400)
            self.assertIn("NDJSON", response.json()["message"])

        asyncio.run(run())

    def test_process_stream_endpoint_rejects_non_monotonic_input_sequence(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)
            body = (
                '{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}\n'
                '{"type":"partial","sequence":3,"timestamp":"2026-05-24T12:00:00Z","payload":{"text":"hello"}}\n'
                '{"type":"completed","sequence":4,"timestamp":"2026-05-24T12:00:00Z","payload":{"reason":"completed","output":"hello"}}'
            )

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/process/stream", content=body)

            self.assertEqual(response.status_code, 400)
            self.assertIn("sequence", response.json()["message"])

        asyncio.run(run())

    def test_get_stream_endpoint_emits_completed_for_decoupled_logical_output(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/process/stream/get",
                    headers={"Accept": "application/x-ndjson"},
                )

            self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))
            events = _events_from_response(response)
            self.assertEqual(
                [event["type"] for event in events],
                ["stream_started", "partial", "partial", "completed", "partial", "completed"],
            )
            self.assertEqual(events[3]["payload"]["reason"], "completed")
            self.assertEqual(events[1]["payload"].keys(), {"bytes_base64", "byte_count", "chunk_index"})
            self.assertEqual(
                events[3]["payload"].keys(),
                {"reason", "output_bytes_base64", "total_bytes", "chunk_count"},
            )
            self.assertEqual(base64.b64decode(events[3]["payload"]["output_bytes_base64"]), b"queued audio")
            self.assertEqual(events[3]["payload"]["total_bytes"], len(b"queued audio"))
            self.assertEqual(events[3]["payload"]["chunk_count"], 2)
            self.assertEqual(base64.b64decode(events[5]["payload"]["output_bytes_base64"]), b"again")
            self.assertEqual(events[5]["payload"]["chunk_count"], 1)

        asyncio.run(run())

    def test_set_stream_endpoint_requires_standard_text_stream_events(self):
        async def run():
            app = FastAPI()
            service = FakeService()
            FastApiAdapter(service, app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                ok_response = await client.post(
                    "/process/stream/set",
                    content=_text_stream_body("one", "two"),
                    headers={
                        "Content-Type": "application/x-ndjson",
                        "Accept": "application/x-ndjson",
                    },
                )
                bad_response = await client.post("/process/stream/set", content="one\ntwo")

            self.assertEqual(ok_response.status_code, 200)
            self.assertEqual([event["type"] for event in _events_from_response(ok_response)], ["stream_started", "completed"])
            self.assertEqual(bad_response.status_code, 200)
            self.assertEqual(_events_from_response(bad_response)[-1]["type"], "error")

        asyncio.run(run())

    def test_set_stream_endpoint_rejects_duplicate_stream_started(self):
        async def run():
            app = FastAPI()
            service = FakeService()
            FastApiAdapter(service, app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)
            body = (
                '{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}\n'
                '{"type":"stream_started","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{}}\n'
            )

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/process/stream/set",
                    content=body,
                    headers={
                        "Content-Type": "application/x-ndjson",
                        "Accept": "application/x-ndjson",
                    },
                )

            self.assertEqual(response.status_code, 200)
            events = _events_from_response(response)
            self.assertEqual(events[-1]["type"], "error")
            self.assertIn("stream_started", events[-1]["payload"]["message"])

        asyncio.run(run())

    def test_set_stream_initializes_before_request_body_ends_and_flushes_on_completed(self):
        class LiveSetService(FakeService):
            def __init__(self):
                self.set_called = asyncio.Event()
                self.text_received = asyncio.Event()
                self.text_items: list[str] = []

            async def set_stream(self, request: SetStreamRequestDto) -> None:
                self.set_called.set()

                async def consume() -> None:
                    async for text in request.text_stream:
                        self.text_items.append(text)
                        self.text_received.set()

                asyncio.create_task(consume())

        async def run():
            app = FastAPI()
            service = LiveSetService()
            FastApiAdapter(service, app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)
            send_partial = asyncio.Event()
            send_completed = asyncio.Event()
            finish_body = asyncio.Event()

            async def live_body():
                yield (
                    '{"type":"stream_started","sequence":1,'
                    '"timestamp":"2026-05-24T12:00:00Z","payload":{}}\n'
                ).encode("utf-8")
                await send_partial.wait()
                yield (
                    '{"type":"partial","sequence":2,'
                    '"timestamp":"2026-05-24T12:00:01Z","payload":{"text":"hello "}}\n'
                ).encode("utf-8")
                await send_completed.wait()
                yield (
                    '{"type":"completed","sequence":3,'
                    '"timestamp":"2026-05-24T12:00:02Z",'
                    '"payload":{"reason":"completed","output":"world"}}\n'
                ).encode("utf-8")
                await finish_body.wait()

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response_task = asyncio.create_task(
                    client.post(
                        "/process/stream/set",
                        content=live_body(),
                        headers={
                            "Content-Type": "application/x-ndjson",
                            "Accept": "application/x-ndjson",
                        },
                    )
                )

                await asyncio.wait_for(service.set_called.wait(), timeout=1)
                self.assertEqual(service.text_items, [])

                send_partial.set()
                await asyncio.sleep(0.01)
                self.assertEqual(service.text_items, [])

                send_completed.set()
                await asyncio.wait_for(service.text_received.wait(), timeout=1)
                self.assertEqual(service.text_items, ["hello world"])

                finish_body.set()
                response = await asyncio.wait_for(response_task, timeout=1)

            self.assertEqual(response.status_code, 200)
            self.assertEqual([event["type"] for event in _events_from_response(response)], ["stream_started", "completed"])

        asyncio.run(run())

    def test_set_stream_default_response_is_sse_and_ndjson_when_requested(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                sse_response = await client.post(
                    "/process/stream/set",
                    content=_text_stream_body("hello"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
                ndjson_response = await client.post(
                    "/process/stream/set",
                    content=_text_stream_body("hello"),
                    headers={
                        "Content-Type": "application/x-ndjson",
                        "Accept": "application/x-ndjson",
                    },
                )

            self.assertTrue(sse_response.headers["content-type"].startswith("text/event-stream"))
            self.assertTrue(ndjson_response.headers["content-type"].startswith("application/x-ndjson"))
            self.assertEqual([event["type"] for event in _events_from_response(sse_response)], ["stream_started", "completed"])
            self.assertEqual([event["type"] for event in _events_from_response(ndjson_response)], ["stream_started", "completed"])

        asyncio.run(run())

    def test_get_stream_default_response_is_ndjson_for_brain_parser(self):
        async def run():
            app = FastAPI()
            FastApiAdapter(FakeService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                default_response = await client.get("/process/stream/get")
                ndjson_response = await client.get(
                    "/process/stream/get",
                    headers={"Accept": "application/x-ndjson"},
                )

            self.assertTrue(default_response.headers["content-type"].startswith("application/x-ndjson"))
            self.assertTrue(ndjson_response.headers["content-type"].startswith("application/x-ndjson"))
            for line in default_response.content.decode("utf-8").splitlines():
                if line.strip():
                    self.assertFalse(line.startswith("event:"))
                    self.assertFalse(line.startswith("data:"))
                    json.loads(line)
            self.assertEqual(_events_from_response(default_response)[0]["type"], "stream_started")
            self.assertEqual(_events_from_response(ndjson_response)[0]["type"], "stream_started")

        asyncio.run(run())

    def test_set_stream_accepts_heartbeat_and_surfaces_upstream_error(self):
        class LiveSetService(FakeService):
            def __init__(self):
                self.text_items: list[str] = []

            async def set_stream(self, request: SetStreamRequestDto) -> None:
                async def consume() -> None:
                    async for text in request.text_stream:
                        self.text_items.append(text)

                asyncio.create_task(consume())

        async def run():
            app = FastAPI()
            service = LiveSetService()
            FastApiAdapter(service, app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)
            body = (
                '{"type":"stream_started","sequence":1,"timestamp":"2026-05-24T12:00:00Z","payload":{}}\n'
                '{"type":"heartbeat","sequence":2,"timestamp":"2026-05-24T12:00:01Z","payload":{}}\n'
                '{"type":"error","sequence":3,"timestamp":"2026-05-24T12:00:02Z","payload":{"code":"upstream_failed","message":"boom","recoverable":false}}\n'
            )

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/process/stream/set",
                    content=body,
                    headers={
                        "Content-Type": "application/x-ndjson",
                        "Accept": "application/x-ndjson",
                    },
                )

            events = _events_from_response(response)
            self.assertEqual([event["type"] for event in events], ["stream_started", "error"])
            self.assertEqual(events[-1]["payload"]["code"], "upstream_failed")
            self.assertEqual(service.text_items, [])

        asyncio.run(run())

    def test_get_stream_emits_audio_stream_error_marker(self):
        class ErrorService(FakeService):
            async def get_stream(self, request: GetStreamRequestDto) -> GetStreamResponseDto:
                return GetStreamResponseDto(
                    audio_stream=_audio_items(
                        b"first",
                        AudioStreamError("synthesis_failed", "boom", True),
                    )
                )

        async def run():
            app = FastAPI()
            FastApiAdapter(ErrorService(), app, InitInboundAdapterDto())
            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/process/stream/get",
                    headers={"Accept": "application/x-ndjson"},
                )

            events = _events_from_response(response)
            self.assertEqual([event["type"] for event in events], ["stream_started", "partial", "error"])
            self.assertEqual(events[-1]["payload"]["code"], "synthesis_failed")
            self.assertIn("boom", events[-1]["payload"]["message"])

        asyncio.run(run())

    def test_stream_can_remain_open_after_completed_with_heartbeat(self):
        async def run():
            generator = _audio_event_stream(
                _audio_chunks(b"done"),
                action="test",
                keep_open_after_completed=True,
                heartbeat_interval_seconds=0,
            )

            events = []
            async for line in generator:
                events.append(json.loads(line))
                if events[-1]["type"] == "heartbeat":
                    break

            self.assertEqual(
                [event["type"] for event in events],
                ["stream_started", "partial", "completed", "heartbeat"],
            )
            self.assertEqual([event["sequence"] for event in events], [1, 2, 3, 4])

            await generator.aclose()

        asyncio.run(run())

    def test_error_event_shape_is_valid_and_sequence_is_monotonic(self):
        async def run():
            events = []
            with patch("infrastructure.inbound.http.fastapi_adapter.logger.exception"):
                async for line in _audio_event_stream(_failing_audio_chunks(), action="test"):
                    events.append(json.loads(line))

            self.assertEqual([event["type"] for event in events], ["stream_started", "partial", "error"])
            self.assertEqual([event["sequence"] for event in events], [1, 2, 3])
            error_payload = events[-1]["payload"]
            self.assertEqual(error_payload["code"], "stream_failed")
            self.assertIn("synthesis failed", error_payload["message"])
            self.assertIs(error_payload["recoverable"], True)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
