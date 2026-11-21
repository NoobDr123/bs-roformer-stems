#!/usr/bin/env python3
"""Runpod Serverless handler: split vocals and instrumental with BS-RoFormer."""
import base64
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

import runpod

MODEL_DIR = os.environ.get("MODEL_DIR", "/models")
MODEL_FILENAME = os.environ.get(
    "MODEL_FILENAME", "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
)
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_DOWNLOAD_BYTES", str(250 * 1024 * 1024)))
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff"}

log = logging.getLogger("stems")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_SEPARATOR = None
_LOAD_S = None
_GPU_NAME = None


def gpu_name():
    global _GPU_NAME
    if _GPU_NAME is not None:
        return _GPU_NAME
    try:
        _GPU_NAME = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True, timeout=10,
        ).strip().splitlines()[0].strip()
    except Exception as e:
        _GPU_NAME = f"unknown ({e.__class__.__name__})"
    return _GPU_NAME


def _set_output(obj, output_dir, output_format):
    """audio-separator keeps output_dir on both Separator and model_instance."""
    if obj is None:
        return
    try:
        obj.output_dir = output_dir
    except Exception:
        pass
    try:
        obj.output_format = output_format
    except Exception:
        pass


def retarget_separator(sep, output_dir, output_format):
    _set_output(sep, output_dir, output_format)
    _set_output(getattr(sep, "model_instance", None), output_dir, output_format)


def get_separator(output_dir, output_format):
    """Load the baked model once; reuse it and retarget the output dir."""
    global _SEPARATOR, _LOAD_S
    if _SEPARATOR is None:
        from audio_separator.separator import Separator
        t0 = time.time()
        log.info("loading %s from %s", MODEL_FILENAME, MODEL_DIR)
        sep = Separator(
            log_level=logging.INFO,
            model_file_dir=MODEL_DIR,
            output_dir=output_dir,
            output_format=output_format,
        )
        sep.load_model(model_filename=MODEL_FILENAME)
        _SEPARATOR = sep
        _LOAD_S = round(time.time() - t0, 2)
        log.info("model loaded in %ss on %s", _LOAD_S, gpu_name())
    retarget_separator(_SEPARATOR, output_dir, output_format)
    return _SEPARATOR


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def is_video(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return True
    if ext in AUDIO_EXTS:
        return False
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return "video" in (r.stdout or "").lower()


def extract_audio(src, dest_wav):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "2",
         "-ar", "44100", "-c:a", "pcm_s16le", dest_wav],
        check=True, capture_output=True,
    )


def download_url(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "bs-roformer-stems/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        n = 0
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            n += len(chunk)
            if n > MAX_DOWNLOAD_BYTES:
                raise ValueError(f"download exceeded {MAX_DOWNLOAD_BYTES} bytes")
            f.write(chunk)
    return n


def write_b64(data, dest):
    raw = base64.b64decode(data)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"base64 payload exceeded {MAX_DOWNLOAD_BYTES} bytes")
    with open(dest, "wb") as f:
        f.write(raw)
    return len(raw)


def classify_stem(path):
    name = os.path.basename(path).lower()
    if "vocal" in name:
        return "vocals"
    if "instrument" in name or "no_vocal" in name or "karaoke" in name:
        return "instrumental"
    if name.endswith("_other") or "(other)" in name or "_other_" in name:
        return "instrumental"
    return None


def read_b64(path):
    with open(path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode(), len(data)


def transcode(src, dest):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, dest],
        check=True, capture_output=True,
    )


def handler(event):
    inp = event.get("input") or {}
    t_job = time.time()
    fmt = (inp.get("format") or "flac").lower().lstrip(".")
    if fmt not in {"flac", "wav", "mp3", "m4a", "ogg"}:
        return {"error": f"unsupported format {fmt!r}; use flac, wav, mp3, m4a, or ogg"}

    url = inp.get("url") or inp.get("audio_url") or inp.get("video_url")
    b64 = inp.get("audio_b64") or inp.get("file_b64") or inp.get("b64")
    filename = inp.get("filename") or inp.get("name") or ("input.mp4" if url else "input.bin")
    if not url and not b64:
        return {"error": "provide url or audio_b64 (optional filename)"}

    work = tempfile.mkdtemp(prefix="stems-")
    out_dir = os.path.join(work, "out")
    os.makedirs(out_dir, exist_ok=True)
    try:
        src = os.path.join(work, os.path.basename(filename) or "input.bin")
        t0 = time.time()
        if url:
            download_url(url, src)
            source = "url"
        else:
            write_b64(b64, src)
            source = "b64"
        t_download = round(time.time() - t0, 2)

        t0 = time.time()
        audio = src
        if is_video(src):
            audio = os.path.join(work, "audio.wav")
            extract_audio(src, audio)
        t_extract = round(time.time() - t0, 2)
        duration_s = ffprobe_duration(audio)

        t0 = time.time()
        sep = get_separator(out_dir, fmt)
        t_load = _LOAD_S
        # first request pays for load inside this block if it wasn't preloaded
        t_load_here = round(time.time() - t0, 2)

        t0 = time.time()
        outputs = sep.separate(audio)
        t_infer = round(time.time() - t0, 2)

        def list_audio_files(*dirs):
            seen, files = set(), []
            for d in dirs:
                if not d or not os.path.isdir(d):
                    continue
                for f in sorted(os.listdir(d)):
                    path = os.path.join(d, f)
                    if not os.path.isfile(path):
                        continue
                    if os.path.splitext(f)[1].lower() not in {".flac", ".wav", ".mp3", ".m4a", ".ogg"}:
                        continue
                    if path in seen:
                        continue
                    seen.add(path)
                    files.append(path)
            return files

        def resolve_outputs(listed):
            """audio-separator may return basenames, drop extra dots in the
            model name, or write into the preload dir on model_instance."""
            search_dirs = [
                out_dir,
                getattr(sep, "output_dir", None),
                getattr(getattr(sep, "model_instance", None), "output_dir", None),
            ]
            found = []
            for p in listed or []:
                cands = [p]
                for d in search_dirs:
                    if d:
                        cands.append(os.path.join(d, p))
                        cands.append(os.path.join(d, os.path.basename(p)))
                hit = next((c for c in cands if c and os.path.isfile(c)), None)
                if hit:
                    found.append(hit)
            if len(found) < 2:
                found = list_audio_files(*search_dirs)
            return found

        outputs = resolve_outputs(outputs)
        stems = {}
        for p in outputs or []:
            kind = classify_stem(p)
            if kind and kind not in stems:
                stems[kind] = p
        if "vocals" not in stems or "instrumental" not in stems:
            return {
                "error": "separator did not return both vocals and instrumental",
                "outputs": [os.path.basename(p) for p in (outputs or [])],
                "timing": {"download_s": t_download, "extract_s": t_extract,
                           "load_s": t_load, "infer_s": t_infer},
            }

        # Keep the Runpod payload small: if lossless files would be huge, fall back to mp3.
        t0 = time.time()
        result_stems = {}
        used_fmt = fmt
        total_bytes = 0
        files = {}
        for kind, path in stems.items():
            b64s, nbytes = read_b64(path)
            files[kind] = (path, b64s, nbytes)
            total_bytes += nbytes
        if total_bytes > 18 * 1024 * 1024 and fmt != "mp3":
            used_fmt = "mp3"
            files = {}
            total_bytes = 0
            for kind, path in stems.items():
                mp3 = os.path.splitext(path)[0] + ".mp3"
                transcode(path, mp3)
                b64s, nbytes = read_b64(mp3)
                files[kind] = (mp3, b64s, nbytes)
                total_bytes += nbytes
        for kind, (path, b64s, nbytes) in files.items():
            result_stems[kind] = {
                "filename": f"{kind}.{used_fmt}",
                "b64": b64s,
                "bytes": nbytes,
            }
        t_encode = round(time.time() - t0, 2)

        return {
            "ok": True,
            "model": MODEL_FILENAME,
            "model_name": "BS-RoFormer Viperx 1297 (SDR 12.9755)",
            "format": used_fmt,
            "duration_s": duration_s,
            "source": source,
            "gpu": gpu_name(),
            "vocals_filename": result_stems["vocals"]["filename"],
            "instrumental_filename": result_stems["instrumental"]["filename"],
            "vocals_b64": result_stems["vocals"]["b64"],
            "instrumental_b64": result_stems["instrumental"]["b64"],
            "vocals_bytes": result_stems["vocals"]["bytes"],
            "instrumental_bytes": result_stems["instrumental"]["bytes"],
            "timing": {
                "download_s": t_download,
                "extract_s": t_extract,
                "model_load_s": t_load,
                "model_load_this_request_s": t_load_here,
                "infer_s": t_infer,
                "encode_s": t_encode,
                "total_handler_s": round(time.time() - t_job, 2),
            },
        }
    except Exception as e:
        log.exception("handler failed")
        return {"error": f"{type(e).__name__}: {e}", "gpu": gpu_name(),
                "total_handler_s": round(time.time() - t_job, 2)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Preload weights at worker boot so the first job is not stalled on disk I/O
# beyond CUDA/model init (still paid on a fully cold machine).
try:
    get_separator(tempfile.mkdtemp(prefix="stems-boot-"), "flac")
except Exception:
    log.exception("preload failed; will retry on first request")

runpod.serverless.start({"handler": handler})
