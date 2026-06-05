# Live STT Tests

## `test_live_stt.py`

- `test_live_stt_stream_accepts_audio_and_completes`
  starts a real `/process/stream/set` request with finite silent PCM, then opens
  `/process/stream/get` after the shared stream is initialized and verifies the
  output text stream can be consumed to completion.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices/stt
```
