# gpt-4o-transcribe-diarize quick reference

- Input formats: mp3, mp4, mpeg, mpga, m4a, wav, webm.
- Max file size: 25 MB per request.
- response_format options: text, json, diarized_json.
- For audio longer than ~30 seconds, pass chunking_strategy (use "auto" to split into chunks).
- Known speakers: up to 4 references via `known_speaker_names` + `known_speaker_references` (data URLs). Typed kwargs since `openai>=2.4`; older releases required `extra_body`.
- Prompting is not supported for gpt-4o-transcribe-diarize.
