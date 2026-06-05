# Live Attachment Tests

This folder contains opt-in Flow4 attachment checks that call real configured
services. They are skipped unless `RUN_LIVE_MICROSERVICE_TESTS=1` is set.

## `test_live_stream_attachment.py`

- `test_live_text_playback_attachment_uses_real_tts_and_speaker`
  verifies the public text playback attachment through real TTS and speaker.

- `test_live_batch_transcription_attachment_uses_real_stt_batch`
  verifies the public batch transcription attachment through real STT batch.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/flows/attachments
```
