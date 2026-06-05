# Live Speaker Tests

## `test_live_speaker.py`

- `test_live_speaker_stream_accepts_audio`
  sends finite silent PCM to the real speaker service and verifies playback is
  accepted successfully.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices/speaker
```
