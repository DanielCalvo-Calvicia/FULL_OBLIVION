# Mock Speaker Tests

These tests cover the brain service's HTTP contract with the speaker service
using `httpx.MockTransport`.

## `test_speaker_adapter.py`

- `test_speaker_adapter_posts_audio_stream_to_set_endpoint`
  verifies that `play_stream()` posts audio bytes to `/process/stream/set`,
  forwards sample rate and channels, parses the provider message, and returns a
  successful playback response.
- `test_speaker_adapter_accepts_empty_success_body`
  verifies that the STT-style set-only speaker contract does not require a
  streaming response body.
- `test_speaker_adapter_surfaces_set_endpoint_failure`
  verifies that HTTP failures from the set endpoint are surfaced as external
  service errors.

## Run

```powershell
python -m pytest tests/mock/external_microservices/speaker
```
