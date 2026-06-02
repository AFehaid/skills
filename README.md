# skills

Reusable, portable skills for AI agents, backends, and CLIs. Each skill is a
self-contained folder with a `SKILL.md` (for agents) plus runnable scripts, so it
works from Claude/agents, the command line, or as an importable library.

## audio-transcribe-diarize
Speech-to-text **+ speaker diarization** for audio/video. Transcribes with
faster-whisper (default `whisper-large-v3`) and labels who-said-what with pyannote,
then merges them into speaker-tagged **SRT / TXT / JSON**. Runs on **GPU or CPU
automatically** (picks the device and precision based on what's available). Built
for mixed Arabic/English code-switching, but works for any language.

See [`audio-transcribe-diarize/`](audio-transcribe-diarize/) for usage
(README + SKILL.md).
