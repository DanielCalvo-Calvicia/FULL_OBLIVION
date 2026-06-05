# Mock Attachment Tests

This folder tests Flow4 attachment behavior: the places where streams are
actually attached and cleanup decisions are made.

## `test_stream_attachment.py`

- `test_voice_pipeline_stops_before_tts_output_when_stt_produces_no_text`
  verifies that the full attachment path opens microphone and STT, but does not
  open TTS output or speaker playback if STT finishes without usable text.

- `test_transcribe_microphone_attachment_stops_microphone_when_stt_fails`
  verifies that microphone cleanup still runs when the `mic -> stt` attachment
  fails after microphone audio has started.

- `test_batch_transcription_attachment_only_calls_stt_batch`
  verifies that batch transcription uses only the STT batch attachment and does
  not touch microphone, TTS, or speaker boundaries.

## Run

```powershell
python -m pytest tests/mock/flows/attachments
```
