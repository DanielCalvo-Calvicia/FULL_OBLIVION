# Mock Microphone Tests

These tests cover the brain service's HTTP contract with the microphone service
using `httpx.MockTransport`.

## `test_microphone_adapter.py`

- `test_microphone_adapter_starts_stream_and_posts_expected_payload`
  verifies that `start_stream()` sends `POST /start`, includes the expected
  `sample_rate`, `channels`, and `chunk_size` JSON body, keeps the streaming
  response open, and returns the requested sample rate.

- `test_microphone_adapter_stops_stream_and_closes_active_stream`
  verifies that `stop_stream()` sends `POST /stop` after a stream starts and
  clears the active stream reference.

## Run

```powershell
python -m pytest tests/mock/external_microservices/microphone
```
