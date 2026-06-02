#!/usr/bin/env python3
"""
transcribe_diarize.py — portable speech-to-text + speaker diarization.

A single self-contained file so it can be vendored into any backend/agent/app.
Transcribes an audio/video file with faster-whisper (default openai/whisper-large-v3)
and labels who-spoke-when with pyannote (default speaker-diarization-community-1),
then merges them into a speaker-attributed transcript.

Designed for mixed-language audio (e.g. Arabic + English code-switching): language
is auto-detected per file and English embedded in Arabic speech is preserved.

Two ways to use it
------------------
CLI:
    python transcribe_diarize.py input.mp4 --out out/
    python transcribe_diarize.py call.wav --out out/ --num-speakers 2
    python transcribe_diarize.py talk.mp3 --out out/ --no-diarize
    python transcribe_diarize.py rec.m4a --out out/ --device cpu
    # re-render with real names after editing out/<name>.speakers.json:
    python transcribe_diarize.py --apply-speakers out/<name>.json

Library (for other Python backends/agents):
    from transcribe_diarize import process
    result = process("input.mp4", out_dir="out")
    # result is a JSON-serializable dict (see RESULT CONTRACT below)

The CLI also prints the result dict as JSON to stdout (after a RESULT_JSON: marker)
so non-Python callers can parse it.

Requirements: faster-whisper, pyannote.audio>=4, torch (CUDA build for GPU),
soundfile, huggingface_hub, and ffmpeg on PATH. A Hugging Face token with access
to the (gated) pyannote model is needed for diarization — pass --hf-token, set
HF_TOKEN, or `hf auth login` beforehand.

RESULT CONTRACT (dict returned by process() / printed as RESULT_JSON):
{
  "input": str, "audio_wav": str,
  "asr_model": str, "diar_model": str|None, "device": str, "compute_type": str,
  "language": str, "duration_sec": float,
  "diarized": bool, "num_speakers": int,
  "speakers": {"Speaker 1": {"minutes": float, "words": int}, ...},
  "utterances": [{"start": float, "end": float, "speaker": str, "text": str}, ...],
  "outputs": {"srt": path, "txt": path, "json": path, "speakers": path}
}
"""
import argparse
import bisect
import gc
import json
import os
import subprocess
import sys
import tempfile
import time

DEFAULT_ASR = "large-v3"
DEFAULT_DIAR = "pyannote/speaker-diarization-community-1"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def log(msg):
    print(f"[transcribe_diarize] {msg}", file=sys.stderr, flush=True)


def fmt_ts(seconds, sep=","):
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def have_ffmpeg():
    from shutil import which
    return which("ffmpeg") is not None


def extract_audio(input_path, out_wav):
    """Decode any media to 16 kHz mono PCM wav (what the models expect)."""
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg not found on PATH — required to decode audio.")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", input_path, "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", out_wav]
    subprocess.run(cmd, check=True)
    return out_wav


def is_16k_mono_wav(path):
    if not path.lower().endswith(".wav"):
        return False
    try:
        import soundfile as sf
        info = sf.info(path)
        return info.samplerate == 16000 and info.channels == 1
    except Exception:
        return False


def resolve_device(device, compute_type):
    import torch
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def get_token(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    try:
        from huggingface_hub import get_token as _gt
        return _gt()
    except Exception:
        return None


def free_cuda():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# ASR
# --------------------------------------------------------------------------- #
def transcribe(wav, model_name, device, compute_type, beam=5, language=None):
    from faster_whisper import WhisperModel
    log(f"loading ASR '{model_name}' on {device} ({compute_type}) ...")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    t0 = time.perf_counter()
    seg_gen, info = model.transcribe(
        wav, language=language, task="transcribe", beam_size=beam,
        vad_filter=True, condition_on_previous_text=False, word_timestamps=True)
    segments = []
    for s in seg_gen:
        words = ([{"start": w.start, "end": w.end, "word": w.word} for w in s.words]
                 if s.words else None)
        segments.append({"start": s.start, "end": s.end, "text": s.text, "words": words})
    dt = time.perf_counter() - t0
    dur = float(getattr(info, "duration", segments[-1]["end"] if segments else 0.0))
    log(f"ASR done: {len(segments)} segments, lang={info.language}, "
        f"{dt:.0f}s ({dt/max(dur,1):.3f} RTF)")
    del model
    free_cuda()
    return {"segments": segments, "language": info.language, "duration_sec": dur}


# --------------------------------------------------------------------------- #
# Diarization
# --------------------------------------------------------------------------- #
def diarize(wav, model_name, token, device, num_speakers=0, min_speakers=0,
            max_speakers=0):
    import torch
    from pyannote.audio import Pipeline
    log(f"loading diarization '{model_name}' ...")
    pipeline = Pipeline.from_pretrained(model_name, token=token)
    if pipeline is None:
        raise RuntimeError(
            f"Pipeline.from_pretrained returned None for {model_name}. "
            "Usually this means the token lacks access to the gated repo — accept "
            "the model terms and use a token with 'read access to gated repos'.")
    pipeline.to(torch.device(device if device == "cuda" else "cpu"))

    import soundfile as sf
    wav_data, sr = sf.read(wav, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(wav_data.T)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(0, keepdim=True)

    kwargs = {}
    if num_speakers > 0:
        kwargs["num_speakers"] = num_speakers
    if min_speakers > 0:
        kwargs["min_speakers"] = min_speakers
    if max_speakers > 0:
        kwargs["max_speakers"] = max_speakers

    try:
        from pyannote.audio.pipelines.utils.hook import ProgressHook
        hook_cm = ProgressHook()
    except Exception:
        import contextlib
        hook_cm = contextlib.nullcontext()

    t0 = time.perf_counter()
    with hook_cm as hook:
        kw = dict(kwargs)
        if hook is not None:
            kw["hook"] = hook
        out = pipeline({"waveform": waveform, "sample_rate": sr}, **kw)

    # pyannote 4.x returns DiarizeOutput; older returns an Annotation directly.
    if hasattr(out, "speaker_diarization"):
        annotation = (getattr(out, "exclusive_speaker_diarization", None)
                      or out.speaker_diarization)
    else:
        annotation = out

    turns = [{"start": float(t.start), "end": float(t.end), "speaker": spk}
             for t, _, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda x: x["start"])
    log(f"diarization done: {len({t['speaker'] for t in turns})} raw speakers, "
        f"{len(turns)} turns, {time.perf_counter()-t0:.0f}s")
    del pipeline
    free_cuda()
    return turns


# --------------------------------------------------------------------------- #
# Merge ASR words with speaker turns
# --------------------------------------------------------------------------- #
def _assigner(turns):
    starts = [t["start"] for t in turns]
    ends = [t["end"] for t in turns]

    def assign(a, b):
        i = bisect.bisect_left(ends, a)
        best_spk, best_ov = None, 0.0
        while i < len(turns) and starts[i] < b:
            ov = min(b, ends[i]) - max(a, starts[i])
            if ov > best_ov:
                best_ov, best_spk = ov, turns[i]["speaker"]
            i += 1
        if best_spk is not None:
            return best_spk
        mid = (a + b) / 2
        j = bisect.bisect_left(starts, mid)
        cands = []
        if j < len(turns):
            cands.append(turns[j])
        if j > 0:
            cands.append(turns[j - 1])
        if not cands:
            return "SPEAKER_00"
        return min(cands, key=lambda t: abs((t["start"] + t["end"]) / 2 - mid))["speaker"]

    return assign


def _iter_words(segments):
    for s in segments:
        if s.get("words"):
            for w in s["words"]:
                if w.get("start") is not None:
                    yield w["start"], w["end"], w["word"]
        else:
            yield s["start"], s["end"], s["text"]


def merge(asr_segments, turns, max_gap=1.2):
    assign = _assigner(turns) if turns else (lambda a, b: "SPEAKER_00")
    tagged = [(a, b, w, assign(a, b)) for a, b, w in _iter_words(asr_segments)]
    tagged.sort(key=lambda x: x[0])
    utts, cur = [], None
    for a, b, word, spk in tagged:
        if cur is None or spk != cur["speaker"] or a - cur["end"] > max_gap:
            if cur:
                utts.append(cur)
            cur = {"start": a, "end": b, "speaker": spk, "_w": [word]}
        else:
            cur["end"] = b
            cur["_w"].append(word)
    if cur:
        utts.append(cur)
    for u in utts:
        toks = u.pop("_w")
        u["text"] = " ".join(t.strip() for t in toks).strip()
    return utts


def label_speakers(utterances, scheme="Speaker {n}"):
    """Rename raw pyannote labels to generic, talk-time-ranked labels."""
    dur = {}
    for u in utterances:
        dur[u["speaker"]] = dur.get(u["speaker"], 0.0) + (u["end"] - u["start"])
    ranked = sorted(dur, key=lambda k: -dur[k])
    mapping = {spk: scheme.format(n=i) for i, spk in enumerate(ranked, 1)}
    for u in utterances:
        u["speaker"] = mapping[u["speaker"]]
    return utterances, mapping


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def write_outputs(out_prefix, utterances, meta, formats):
    paths = {}
    if "json" in formats:
        p = out_prefix + ".json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump({**meta, "utterances": utterances}, f, ensure_ascii=False, indent=2)
        paths["json"] = p
    if "srt" in formats:
        p = out_prefix + ".srt"
        with open(p, "w", encoding="utf-8") as f:
            for i, u in enumerate(utterances, 1):
                tag = f"{u['speaker']}: " if u.get("speaker") else ""
                f.write(f"{i}\n{fmt_ts(u['start'])} --> {fmt_ts(u['end'])}\n"
                        f"{tag}{u['text']}\n\n")
        paths["srt"] = p
    if "txt" in formats:
        p = out_prefix + ".txt"
        with open(p, "w", encoding="utf-8") as f:
            for u in utterances:
                tag = f"{u['speaker']}: " if u.get("speaker") else ""
                f.write(f"[{fmt_ts(u['start'], sep='.')[:8]}] {tag}{u['text']}\n")
        paths["txt"] = p
    return paths


def speaker_stats(utterances):
    import re
    W = re.compile(r"\w+", re.UNICODE)
    stats = {}
    for u in utterances:
        s = stats.setdefault(u["speaker"], {"minutes": 0.0, "words": 0})
        s["minutes"] += (u["end"] - u["start"]) / 60.0
        s["words"] += len(W.findall(u["text"]))
    return {k: {"minutes": round(float(v["minutes"]), 1), "words": int(v["words"])}
            for k, v in sorted(stats.items(), key=lambda kv: -kv[1]["minutes"])}


# --------------------------------------------------------------------------- #
# Top-level pipeline (library entry point)
# --------------------------------------------------------------------------- #
def process(input_path, out_dir="out", asr_model=DEFAULT_ASR, diar_model=DEFAULT_DIAR,
            device="auto", compute_type="auto", diarize_speakers=True,
            num_speakers=0, min_speakers=0, max_speakers=0, hf_token=None,
            language=None, beam=5, formats=("srt", "txt", "json"),
            keep_wav=False, label_scheme="Speaker {n}"):
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(input_path))[0]
    out_prefix = os.path.join(out_dir, name)
    device, compute_type = resolve_device(device, compute_type)

    # 1) audio
    if is_16k_mono_wav(input_path):
        wav = input_path
        tmp_wav = None
    else:
        wav = os.path.join(out_dir, name + ".16k.wav")
        log(f"extracting audio -> {wav}")
        extract_audio(input_path, wav)
        tmp_wav = wav

    # 2) ASR (then VRAM freed before diarization — one model at a time)
    asr = transcribe(wav, asr_model, device, compute_type, beam=beam, language=language)

    # 3) diarization (optional / best-effort)
    turns, used_diar = [], None
    if diarize_speakers:
        token = get_token(hf_token)
        try:
            turns = diarize(wav, diar_model, token, device, num_speakers,
                            min_speakers, max_speakers)
            used_diar = diar_model
        except Exception as e:
            log(f"DIARIZATION SKIPPED ({type(e).__name__}: {str(e)[:160]}). "
                "Producing transcript without speaker labels. For diarization, accept "
                "the pyannote terms and provide a token with gated-repo read access.")
            turns = []

    # 4) merge + label
    utts = merge(asr["segments"], turns, max_gap=1.2)
    diarized = bool(turns)
    if diarized:
        utts, mapping = label_speakers(utts, scheme=label_scheme)
    else:
        for u in utts:
            u["speaker"] = ""  # no speakers -> plain transcript
        mapping = {}

    stats = speaker_stats(utts) if diarized else {}
    meta = {
        "input": os.path.abspath(input_path),
        "audio_wav": os.path.abspath(wav),
        "asr_model": asr_model, "diar_model": used_diar,
        "device": device, "compute_type": compute_type,
        "language": asr["language"], "duration_sec": round(asr["duration_sec"], 2),
        "diarized": diarized, "num_speakers": len(stats),
        "speakers": stats,
    }
    paths = write_outputs(out_prefix, utts, meta, formats)

    # rename map (raw pyannote label -> display) so users can re-label later
    if diarized:
        spk_path = out_prefix + ".speakers.json"
        # invert mapping to {display_label: editable_name}
        with open(spk_path, "w", encoding="utf-8") as f:
            json.dump({disp: disp for disp in
                       sorted(set(mapping.values()),
                              key=lambda d: int(d.split()[-1]) if d.split()[-1].isdigit() else 999)},
                      f, ensure_ascii=False, indent=2)
        paths["speakers"] = spk_path

    if tmp_wav and not keep_wav:
        try:
            os.remove(tmp_wav)
        except OSError:
            pass
        meta["audio_wav"] = None

    result = {**meta, "utterances": utts, "outputs": paths}
    return result


def apply_speakers(result_json, speakers_json=None, formats=("srt", "txt")):
    """Re-render srt/txt from a result .json after the user edits the speakers map."""
    with open(result_json, encoding="utf-8") as f:
        data = json.load(f)
    prefix = os.path.splitext(result_json)[0]
    speakers_json = speakers_json or (prefix + ".speakers.json")
    names = {}
    if os.path.exists(speakers_json):
        with open(speakers_json, encoding="utf-8") as f:
            names = json.load(f)
    utts = data["utterances"]
    for u in utts:
        u["speaker"] = names.get(u["speaker"], u["speaker"])
    paths = write_outputs(prefix, utts, {k: v for k, v in data.items()
                                         if k != "utterances"}, formats)
    log(f"re-rendered with names {names} -> {list(paths.values())}")
    return paths


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Transcribe + speaker-diarize an audio/video file.")
    ap.add_argument("input", nargs="?", help="audio/video file (any ffmpeg format)")
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    ap.add_argument("--model", default=DEFAULT_ASR, help=f"ASR model (default: {DEFAULT_ASR})")
    ap.add_argument("--diar-model", default=DEFAULT_DIAR)
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute-type", default="auto",
                    help="auto|float16|int8_float16|int8 (auto: float16 on GPU, int8 on CPU)")
    ap.add_argument("--no-diarize", action="store_true", help="transcript only, no speakers")
    ap.add_argument("--num-speakers", type=int, default=0, help="force exact speaker count")
    ap.add_argument("--min-speakers", type=int, default=0)
    ap.add_argument("--max-speakers", type=int, default=0)
    ap.add_argument("--hf-token", default=None, help="HF token (else HF_TOKEN / cached login)")
    ap.add_argument("--language", default=None, help="force language code (default: auto-detect)")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--formats", default="srt,txt,json")
    ap.add_argument("--keep-wav", action="store_true", help="keep the extracted 16k wav")
    ap.add_argument("--label-scheme", default="Speaker {n}",
                    help="speaker label template, e.g. 'Speaker {n}' or 'S{n}'")
    ap.add_argument("--apply-speakers", metavar="RESULT_JSON",
                    help="re-render srt/txt from an existing result .json using its "
                         ".speakers.json name map (run after editing the names)")
    args = ap.parse_args()

    if args.apply_speakers:
        apply_speakers(args.apply_speakers)
        return

    if not args.input:
        ap.error("input file is required (or use --apply-speakers)")

    result = process(
        args.input, out_dir=args.out, asr_model=args.model, diar_model=args.diar_model,
        device=args.device, compute_type=args.compute_type,
        diarize_speakers=not args.no_diarize, num_speakers=args.num_speakers,
        min_speakers=args.min_speakers, max_speakers=args.max_speakers,
        hf_token=args.hf_token, language=args.language, beam=args.beam,
        formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
        keep_wav=args.keep_wav, label_scheme=args.label_scheme)

    log(f"outputs: {result['outputs']}")
    if result["diarized"]:
        log(f"speakers: {result['speakers']}")
    # machine-readable result for non-Python callers
    print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
