# Mock TTS Tests

These tests cover the brain service's HTTP contract with the TTS service using
`httpx.MockTransport`.

## `test_tts_adapter.py`

- `test_tts_adapter_posts_single_text_stream`
  verifies that `set_stream()` posts a single text payload with sample rate and
  channel parameters.

- `test_tts_adapter_posts_text_iterator_as_newline_chunks`
  verifies that `set_text_stream()` trims empty values and sends newline
  separated text chunks.

- `test_tts_adapter_gets_audio_stream`
  verifies that `get_stream()` opens the TTS audio output stream with the
  expected audio settings.

## Run

```powershell
python -m pytest tests/mock/external_microservices/tts
```
