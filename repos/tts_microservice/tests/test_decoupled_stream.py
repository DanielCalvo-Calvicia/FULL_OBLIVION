"""
Verification test for the decoupled streaming endpoints.

Usage:
    1. Start the TTS microservice:  python main.py
    2. Run this test:               python tests/test_decoupled_stream.py

This script:
    - POSTs a multi-line text block to POST /process/stream/set
    - GETs synthesized audio events from GET /process/stream/get
    - Validates that partial audio events and a completed event are emitted.
"""

import asyncio
import base64
import json
import httpx
import sys
import os

from infrastructure.config import resolve_environment
from infrastructure.logger import configure_logging, get_logger

BASE_URL = os.getenv("TTS_TEST_BASE_URL", "http://127.0.0.1:8002")
logger = get_logger(__name__)


def text_stream_body(*chunks: str) -> str:
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
    return "\n".join(json.dumps(event) for event in events) + "\n"


async def TestDecoupledStream():
    """End-to-end test for set_stream / get_stream decoupled flow."""

    textPayload = text_stream_body(
        "Hello, this is the first sentence.",
        "This is the second sentence for streaming.",
        "And a third sentence to verify multi-chunk behaviour.",
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        logger.info("[1/3] Sending text to POST /process/stream/set ...")
        setResponse = await client.post(
            f"{BASE_URL}/process/stream/set",
            content=textPayload,
            headers={"Content-Type": "application/x-ndjson"},
        )

        assert setResponse.status_code == 202, (
            f"Expected 202 Accepted, got {setResponse.status_code}: {setResponse.text}"
        )
        logger.info("Received %s Accepted", setResponse.status_code)

        await asyncio.sleep(0.5)

        logger.info("[2/3] Streaming audio events from GET /process/stream/get ...")
        totalBytes = 0
        partialCount = 0
        eventTypes = []

        async with client.stream("GET", f"{BASE_URL}/process/stream/get") as getResponse:
            assert getResponse.status_code == 200, (
                f"Expected 200 OK, got {getResponse.status_code}"
            )

            async for line in getResponse.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                eventTypes.append(event.get("type"))
                if event.get("type") == "partial":
                    totalBytes += len(base64.b64decode(event.get("payload", {}).get("bytes_base64", "")))
                    partialCount += 1
                if event.get("type") == "completed":
                    break

        logger.info("[3/3] Validation:")
        logger.info("Event types received: %s", eventTypes)
        logger.info("Partial events received: %s", partialCount)
        logger.info("Total bytes: %s", totalBytes)

        assert eventTypes[:1] == ["stream_started"], "Expected stream_started as first event"
        assert "completed" in eventTypes, "Expected completed event"
        assert partialCount > 0, "Expected at least one partial event but got none"
        assert totalBytes > 0, "Expected non-zero audio data but got 0 bytes"

        logger.info("PASS: Decoupled stream test completed successfully")


if __name__ == "__main__":
    configure_logging(resolve_environment())
    try:
        asyncio.run(TestDecoupledStream())
    except AssertionError as e:
        logger.error("FAIL: %s", e)
        sys.exit(1)
    except httpx.ConnectError:
        logger.error(
            "Could not connect to %s. Is the TTS microservice running?",
            BASE_URL,
        )
        sys.exit(1)
