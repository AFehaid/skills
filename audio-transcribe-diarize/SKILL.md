---
name: audio-transcribe-diarize
description: >-
  Transcribe an audio or video file to text AND label who said what (speaker
  diarization), producing speaker-tagged SRT/TXT/JSON. Built for mixed-language
  audio, especially Arabic + English code-switching, but works for any language.
  Use this skill WHENEVER the user wants to transcribe, caption, or subtitle a
  recording; get a transcript of a podcast / meeting / interview / lecture / call /
  voice note / video; produce an .srt or .vtt; or figure out "who said what" /
  separate speakers in audio — even if they don't say the word "diarization".
  Trigger on phrases like "transcribe this", "make subtitles", "get the text from
  this video/audio", "who's talking when", "label the speakers", or any audio/video
  file handed over for turning speech into text.
---

# Audio transcribe + diarize

Turns any audio/video file into a **speaker-labeled transcript** using
faster-whisper (default `large-v3`) for the words and pyannote
(`speaker-diarization-community-1`) for who-spoke-when, merged by word-level
timestamps. Self-contained engine in `scripts/transcribe_diarize.py` — usable from
the CLI, importable as a library, and emits a machine-readable JSON result so other
backends/agents can consume it.

## When to use
Any request to transcribe / caption / subtitle audio or video, get a meeting or
podcast transcript, extract speech to text, or separate/label speakers. Mixed
Arabic/English is the sweet spot, but it's general.

## Quick start
The engine is one file. Run it with a Python env that has the deps (see
`requirements.txt`; install into a venv with a CUDA build of torch for GPU speed):

```bash
python scripts/transcribe_diarize.py INPUT --out OUTDIR
```

Examples:
```bash
# podcast/video -> speaker-labeled srt+txt+json
python scripts/transcribe_diarize.py podcast.mp4 --out results

# a 2-person call, force 2 speakers
python scripts/transcribe_diarize.py call.wav --out results --num-speakers 2

# transcript only (skip diarization)
python scripts/transcribe_diarize.py lecture.m4a --out results --no-diarize

# CPU-only machine
python scripts/transcribe_diarize.py note.mp3 --out results --device cpu
```

## How to drive it (for Claude)
1. **Confirm the input path** and an output dir. Any ffmpeg-readable format works
   (mp4/mkv/mp3/m4a/wav/…); the tool extracts 16 kHz mono internally.
2. **Pick the env.** If a project venv with the deps already exists, use its python.
   Otherwise create one (`python -m venv .venv && .venv/bin/pip install -r requirements.txt`)
   and install a torch build matching the machine's CUDA (CPU torch also works, slower).
   Verify GPU with `python -c "import torch;print(torch.cuda.is_available())"`.
3. **Diarization needs a Hugging Face token** with access to the gated pyannote model.
   If the user hasn't accepted terms / the token lacks gated access, diarization is
   **skipped gracefully** and you still get a plain transcript. To enable it: the user
   accepts terms at the model page and provides a token via `--hf-token`, `HF_TOKEN`,
   or `hf auth login`. The token needs "read access to public gated repos".
4. **Run it**, then read the `RESULT_JSON:` line on stdout (a dict — see the contract
   in the script header) to report duration, language, speakers, and output paths.
5. **VRAM:** the tool loads one model at a time (frees the ASR model before loading the
   diarizer), so it fits comfortably on ~6 GB+ GPUs at float16. For long audio this is
   the default; nothing extra needed.

## Speaker labels & renaming
Speakers come out generic and **ranked by talk time**: `Speaker 1`, `Speaker 2`, …
(Speaker 1 talks most). A `<name>.speakers.json` map is written alongside. To apply
real names: edit that file's values (e.g. `"Speaker 1": "Host"`) and re-render:
```bash
python scripts/transcribe_diarize.py --apply-speakers OUTDIR/<name>.json
```

## Key options
- `--no-diarize` — transcript only (no speakers)
- `--num-speakers N` / `--min-speakers` / `--max-speakers` — constrain clustering
  (use `--num-speakers` when you know the count; cleans up spurious tiny speakers)
- `--model` — ASR model (default `large-v3`; `large-v3-turbo` is ~2.5× faster, similar quality)
- `--device auto|cuda|cpu`, `--compute-type auto|float16|int8_float16|int8`
- `--language` — force a language code instead of auto-detect
- `--label-scheme` — e.g. `'Speaker {n}'` (default) or `'S{n}'`

## Notes
- Output formats via `--formats srt,txt,json` (default all three).
- The JSON output is the integration contract for other apps/agents — see the
  RESULT CONTRACT block at the top of `scripts/transcribe_diarize.py`.
- See `README.md` for library usage and full setup/troubleshooting.
