# Mock STT Tests

These tests cover the brain service's HTTP contract with the STT service using
`httpx.MockTransport`.

## `test_stt_adapter.py`

- `test_stt_adapter_posts_audio_stream_input`
  verifies that `set_stream()` posts audio bytes to `/process/stream/set` and
  forwards stream settings as query parameters.

- `test_stt_adapter_can_replace_decoupled_stream_with_second_set_request`
  verifies the README-described replacement behavior by sending two separate
  `/process/stream/set` requests through the adapter. The STT service owns the
  cancellation/replacement; the brain adapter must simply issue each new set
  request cleanly.

- `test_stt_adapter_gets_and_parses_sse_text_stream`
  verifies that `get_stream()` opens `/process/stream/get`, forwards all stream
  query settings, and parses `data:` SSE lines into text segments.

- `test_stt_adapter_get_stream_before_set_surfaces_endpoint_not_found`
  verifies the README-described behavior where `/process/stream/get` before any
  `/process/stream/set` returns 404. The adapter exposes that as
  `ExternalServiceUnavailableError`.

- `test_stt_adapter_treats_incomplete_chunked_close_as_stream_completion`
  verifies the defensive behavior for SSE responses that close without a final
  HTTP chunk. This keeps debugging cleaner when a real STT stream ends abruptly
  after all available events were sent.

- `test_stt_adapter_posts_batch_audio_and_parses_text`
  verifies that `process_batch()` sends raw audio to `/process/batch`, includes
  the sample rate, and maps the JSON text response into `STTBatchResponseDto`.

## Run

```powershell
python -m pytest tests/mock/external_microservices/stt
```
