"""
End-to-end integration test for the Microphone Microservice.

This script boots the real FastAPI app, exercises the public HTTP API, and
shuts the server down gracefully.

Usage:
    python tests/simple.py
"""

import asyncio
import base64
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

import httpx
import uvicorn

from composition_root.containers.container import BuildContainer


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


HOST = "127.0.0.1"
PORT = find_free_port()
BASE_URL = f"http://{HOST}:{PORT}"
STREAM_READ_SECONDS = 4
STARTUP_TIMEOUT = 10
STANDARD_EVENT_TYPES = {"stream_started", "partial", "completed", "heartbeat", "error"}


async def start_server() -> tuple[uvicorn.Server, asyncio.Task]:
    container = BuildContainer(name="Test Microservice")
    app = container.microphone_dependency.adapter_inbound.get_app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    async with httpx.AsyncClient(timeout=2.0) as client:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{BASE_URL}/health")
                if resp.status_code == 200:
                    return server, task
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.2)

    raise RuntimeError(f"Server did not become healthy within {STARTUP_TIMEOUT}s")


async def stop_server(server: uvicorn.Server, task: asyncio.Task) -> None:
    server.should_exit = True
    await task


def print_header(title: str) -> None:
    print(f"\n{'-' * 50}")
    print(f"  {title}")
    print(f"{'-' * 50}")


def print_result(label: str, success: bool, detail: str = "") -> None:
    status = "OK" if success else "FAIL"
    message = f"  {status} {label}"
    if detail:
        message += f" -> {detail}"
    print(message)


def validate_stream_event(event: dict, expected_sequence: int) -> None:
    if set(event) != {"type", "sequence", "timestamp", "payload"}:
        raise ValueError(f"Invalid stream event fields: {event}")
    if event["type"] not in STANDARD_EVENT_TYPES:
        raise ValueError(f"Unsupported stream event type: {event['type']}")
    if event["sequence"] != expected_sequence:
        raise ValueError(f"Expected sequence {expected_sequence}, got {event['sequence']}")
    if not isinstance(event["payload"], dict):
        raise ValueError("Stream event payload must be an object")
    if not event["timestamp"].endswith("Z"):
        raise ValueError("Stream event timestamp must be UTC and end with Z")
    datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))

    payload = event["payload"]
    if event["type"] == "stream_started" and payload != {}:
        raise ValueError("stream_started payload must be empty")
    if event["type"] == "partial":
        if set(payload) != {"bytes_base64"}:
            raise ValueError("partial audio payload must contain only bytes_base64")
        base64.b64decode(payload["bytes_base64"], validate=True)
    if event["type"] == "completed":
        if set(payload) != {"reason", "output_bytes_base64"}:
            raise ValueError("completed audio payload must contain reason and output_bytes_base64")
        if payload.get("reason") != "completed":
            raise ValueError("completed event reason must be completed")
        base64.b64decode(payload["output_bytes_base64"], validate=True)
    if event["type"] == "error":
        if set(payload) != {"code", "message", "recoverable"}:
            raise ValueError("error payload must contain code, message, and recoverable")


def parse_sse_frame(frame: str) -> dict:
    lines = frame.splitlines()
    if len(lines) != 1:
        raise ValueError(f"SSE frame must contain exactly one data line: {frame!r}")
    if not lines[0].startswith("data:") or lines[0].startswith("data: "):
        raise ValueError(f"SSE value must be exactly standard JSON after data:: {frame!r}")
    return json.loads(lines[0][len("data:"):])


async def read_stream_events_for(response: httpx.Response, seconds: float) -> dict:
    content_type = response.headers.get("content-type", "")
    is_ndjson = content_type.startswith("application/x-ndjson")
    is_sse = content_type.startswith("text/event-stream")
    if not (is_ndjson or is_sse):
        raise ValueError(f"Unexpected stream content-type: {content_type}")

    events: list[dict] = []
    deadline = time.monotonic() + seconds
    line_iter = response.aiter_lines().__aiter__()
    sse_frame_lines: list[str] = []

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = await asyncio.wait_for(anext(line_iter), timeout=remaining)
        except asyncio.TimeoutError:
            break
        except StopAsyncIteration:
            break

        if is_sse:
            if line == "":
                if sse_frame_lines:
                    event = parse_sse_frame("\n".join(sse_frame_lines))
                    events.append(event)
                    validate_stream_event(event, len(events))
                    sse_frame_lines = []
                continue
            sse_frame_lines.append(line)
            continue

        if not line:
            continue
        event = json.loads(line)
        events.append(event)
        validate_stream_event(event, len(events))

    if sse_frame_lines:
        event = parse_sse_frame("\n".join(sse_frame_lines))
        events.append(event)
        validate_stream_event(event, len(events))

    event_types = [event["type"] for event in events]
    if not event_types or event_types[0] != "stream_started":
        raise ValueError(f"Stream did not begin with stream_started: {event_types}")

    return {
        "count": len(events),
        "types": event_types,
        "partials": event_types.count("partial"),
        "completed": event_types.count("completed"),
        "errors": event_types.count("error"),
    }


async def test_health(client: httpx.AsyncClient) -> bool:
    print_header("1. Health Check -> GET /health")
    resp = await client.get(f"{BASE_URL}/health")
    body = resp.json()
    ok = resp.status_code == 200 and body.get("status") == "success"
    print_result("Health", ok, f"status={resp.status_code} body={body}")
    return ok


async def test_available(client: httpx.AsyncClient, step: str, expected: bool) -> bool:
    print_header(f"{step}. Availability Check -> GET /available (expect={expected})")
    resp = await client.get(f"{BASE_URL}/available")
    body = resp.json()
    actual = body.get("data")
    ok = resp.status_code == 200 and actual == expected
    print_result("Available", ok, f"expected={expected} actual={actual}")
    return ok


async def test_start(client: httpx.AsyncClient, *, sse: bool = False) -> bool:
    label = "Start SSE" if sse else "Start NDJSON"
    print_header(f"{label} -> POST /start")
    headers = {"Accept": "text/event-stream"} if sse else None
    async with client.stream(
        "POST",
        f"{BASE_URL}/start",
        headers=headers,
        json={"sample_rate": 16000, "channels": 1, "chunk_size": 1024},
    ) as resp:
        sample_rate = resp.headers.get("x-sample-rate", "?")
        status_hdr = resp.headers.get("x-status", "?")
        summary = await read_stream_events_for(resp, STREAM_READ_SECONDS)

    ok = resp.status_code == 200 and summary["count"] > 0 and summary["errors"] == 0
    print_result(
        label,
        ok,
        f"status={resp.status_code} events={summary['types']} sample_rate={sample_rate} x-status={status_hdr}",
    )
    return ok


async def test_removed_stream_endpoint(client: httpx.AsyncClient) -> bool:
    print_header("Removed Stream Endpoint -> GET /stream")
    resp = await client.get(f"{BASE_URL}/stream")
    ok = resp.status_code == 404
    print_result("Removed /stream", ok, f"status={resp.status_code}")
    return ok


async def test_stop(client: httpx.AsyncClient, step: str) -> bool:
    print_header(f"{step}. Stop Microphone -> POST /stop")
    resp = await client.post(f"{BASE_URL}/stop", json={})
    body = resp.json()
    ok = resp.status_code == 200 and body.get("status") == "success"
    print_result("Stop", ok, f"status={resp.status_code} body={body}")
    return ok


async def run_tests() -> None:
    print("\n" + "=" * 50)
    print("  Microphone Microservice - E2E Test")
    print("=" * 50)

    print_header("Starting server...")
    server, server_task = await start_server()
    print_result("Server", True, f"listening on {BASE_URL}")

    results: list[bool] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            results.append(await test_health(client))
            results.append(await test_available(client, "2", expected=False))
            results.append(await test_start(client, sse=False))
            results.append(await test_available(client, "4", expected=True))
            results.append(await test_stop(client, "5"))
            results.append(await test_available(client, "6", expected=False))
            results.append(await test_start(client, sse=True))
            results.append(await test_stop(client, "8"))
            results.append(await test_removed_stream_endpoint(client))
            results.append(await test_available(client, "10", expected=False))
    finally:
        print_header("Stopping server...")
        await stop_server(server, server_task)
        print_result("Server", True, "shut down gracefully")

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 50)
    if passed == total:
        print(f"  ALL PASSED ({passed}/{total})")
    else:
        print(f"  FAILURES ({passed}/{total} passed)")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
