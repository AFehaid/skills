# audio-transcribe-diarize

Portable **speech-to-text + speaker diarization** for audio/video. One self-contained
Python file (`scripts/transcribe_diarize.py`) that you can run as a CLI, import as a
library, or call from any backend/agent and parse its JSON output. It is also a Claude
Code/Agent **skill** (see `SKILL.md`), but it does not depend on Claude — use it
anywhere.

- **ASR:** faster-whisper / CTranslate2, default `openai/whisper-large-v3`
- **Diarization:** pyannote `speaker-diarization-community-1`
- **Merge:** word-level timestamps → speaker turns by max overlap → utterances
- **Output:** `.srt`, `.txt`, `.json` with generic, talk-time-ranked `Speaker N` labels
- **Built for** mixed-language audio (Arabic + English code-switching), general otherwise

## Why this exists
It's the reusable core extracted from a benchmark of several Arabic/English ASR models
(whisper-large-v3/turbo, Arabic fine-tunes, Qwen3-ASR). large-v3 + pyannote won for
faithful code-switching transcription, so that's the default stack here.

## Install
```bash
python -m venv .venv
. .venv/bin/activate
# GPU (pick the index-url for your CUDA), or omit --index-url for CPU-only torch:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
# ffmpeg must be on PATH (e.g. `sudo dnf install ffmpeg` / `apt install ffmpeg`)
```
Verify GPU: `python -c "import torch;print(torch.cuda.is_available())"`.

### Hugging Face token (for diarization)
The pyannote model is **gated**. To enable speaker labels:
1. Accept terms at https://huggingface.co/pyannote/speaker-diarization-community-1
2. Use a token with **"Read access to contents of all public gated repos"** (fine-grained)
   or a classic **Read** token. Provide it via `--hf-token`, `HF_TOKEN`, or `hf auth login`.

Without a valid gated token, diarization is **skipped gracefully** and you still get a
plain transcript (no speaker labels).

## CLI
```bash
python scripts/transcribe_diarize.py INPUT --out OUTDIR [options]
```
Common options:
| Option | Meaning |
|---|---|
| `--out DIR` | output directory (default `out`) |
| `--no-diarize` | transcript only, no speaker labels |
| `--num-speakers N` | force exact speaker count (cleans up spurious speakers) |
| `--min-speakers` / `--max-speakers` | bound the speaker count |
| `--model` | ASR model (default `large-v3`; `large-v3-turbo` faster) |
| `--device auto\|cuda\|cpu` | compute device |
| `--compute-type auto\|float16\|int8_float16\|int8` | precision |
| `--language CODE` | force language (default: auto-detect) |
| `--formats srt,txt,json` | which outputs to write |
| `--label-scheme '{n}'` | label template, e.g. `'Speaker {n}'`, `'S{n}'` |
| `--apply-speakers RESULT.json` | re-render after editing the `.speakers.json` names |

### Rename speakers
Labels are generic and ranked by talk time (`Speaker 1` talks most). Edit
`OUTDIR/<name>.speakers.json` (e.g. `"Speaker 1": "Host"`) then:
```bash
python scripts/transcribe_diarize.py --apply-speakers OUTDIR/<name>.json
```

## Library / backend use
```python
from transcribe_diarize import process

result = process(
    "interview.mp4",
    out_dir="results",
    num_speakers=2,          # optional
    # device="cpu",          # optional; defaults to auto
    # hf_token="hf_...",     # optional; else env/cached
)
print(result["language"], result["num_speakers"])
for u in result["utterances"][:3]:
    print(u["start"], u["speaker"], u["text"])
```

`process(...)` returns a JSON-serializable dict. The CLI also prints it after a
`RESULT_JSON:` marker on stdout, so non-Python callers can do:
```bash
python scripts/transcribe_diarize.py in.mp4 --out out 2>/dev/null \
  | sed -n 's/^RESULT_JSON://p' | jq .num_speakers
```

### Result contract
```jsonc
{
  "input": "...", "audio_wav": "...|null",
  "asr_model": "large-v3", "diar_model": "pyannote/...|null",
  "device": "cuda", "compute_type": "float16",
  "language": "ar", "duration_sec": 10864.3,
  "diarized": true, "num_speakers": 3,
  "speakers": { "Speaker 1": {"minutes": 90.3, "words": 9650}, ... },
  "utterances": [ {"start": 0.0, "end": 5.1, "speaker": "Speaker 1", "text": "..."}, ... ],
  "outputs": { "srt": "...", "txt": "...", "json": "...", "speakers": "..." }
}
```

## Use as a Claude skill
Place this directory where your agent discovers skills (e.g. `~/.claude/skills/` or a
project `.claude/skills/`). `SKILL.md` tells the agent when and how to invoke it.

## Notes & tips
- **One model in VRAM at a time:** the ASR model is freed before the diarizer loads,
  so it fits on ~6 GB+ GPUs at float16.
- **Cleaner speaker split:** if you get tiny spurious speakers (music/noise), re-run with
  `--num-speakers N` when you know the real count.
- **Speed:** `--model large-v3-turbo` is ~2.5× faster with very similar quality.
- **Languages:** auto-detected per file; pass `--language` to force.
