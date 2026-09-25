param(
    [string]$Container = "oblivion-brain",
    [string]$MicrophoneUrl = "http://host.docker.internal:8000",
    [int]$Seconds = 5
)

$ErrorActionPreference = "Stop"

$python = @"
import json
import socket
import sys
import time
import urllib.request

base_url = sys.argv[2].rstrip("/")
seconds = int(sys.argv[3])

def read_url(path, **kwargs):
    with urllib.request.urlopen(base_url + path, timeout=10, **kwargs) as response:
        body = response.read()
        print(path, response.status, body[:300])

print("container can resolve and call Windows microphone:")
read_url("/health")

payload = json.dumps({"sample_rate": 16000, "channels": 1, "chunk_size": 1024}).encode("utf-8")
request = urllib.request.Request(
    base_url + "/start",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/x-ndjson",
    },
    method="POST",
)

print(f"opening stream for {seconds}s...")
started = time.time()
lines = 0
bytes_seen = 0
audio_events = 0
stream_ended = False
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        print("stream status", response.status)
        response.fp.raw._sock.settimeout(0.5)
        while time.time() - started < seconds:
            try:
                line = response.readline()
            except (socket.timeout, OSError) as exc:
                print("timed out waiting for microphone event", type(exc).__name__, str(exc))
                break
            if not line:
                stream_ended = True
                print("stream ended by server")
                break
            lines += 1
            bytes_seen += len(line)
            preview = line[:220].decode("utf-8", errors="replace").strip()
            print(f"line={lines} bytes={len(line)} total={bytes_seen} preview={preview!r}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                print("invalid json line", exc)
                continue
            event_type = event.get("type")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "partial" and payload.get("bytes_base64"):
                audio_events += 1
                print("audio event received", event_type, "base64_chars", len(payload["bytes_base64"]))
            elif event_type == "completed" and payload.get("output_bytes_base64"):
                audio_events += 1
                print("audio event received", event_type, "base64_chars", len(payload["output_bytes_base64"]))
finally:
    try:
        stop_request = urllib.request.Request(base_url + "/stop", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(stop_request, timeout=10) as response:
            print("stop status", response.status)
    except Exception as exc:
        print("stop failed", type(exc).__name__, str(exc))

print(f"summary lines={lines} bytes={bytes_seen} audio_events={audio_events} stream_ended={stream_ended}")
if audio_events == 0:
    print("NO_AUDIO_EVENTS_SEEN")
"@

$encodedPython = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($python))
$runner = "import base64,sys; exec(base64.b64decode(sys.argv[1]).decode())"
docker exec $Container python -c $runner $encodedPython $MicrophoneUrl $Seconds
