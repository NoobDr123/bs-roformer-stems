#!/usr/bin/env python3
"""Client for the BS-RoFormer vocals/instrumental Runpod Serverless endpoint.

  python3 client.py health
  python3 client.py separate test/test_ad.mp4 -o test/out
  python3 client.py separate https://example.com/ad.mp4 -o test/out --format flac

Auth: RUNPOD_API_KEY. Optional STEM_ENDPOINT overrides the endpoint id.
Local files are sent as base64 (audio is extracted first when the source is video).
URLs are fetched by the worker.
"""
import argparse, base64, json, os, subprocess, sys, tempfile, time
import requests

ENDPOINT_ID = os.environ.get("STEM_ENDPOINT", os.environ.get("STEMS_ENDPOINT", ""))
HERE = os.path.dirname(os.path.abspath(__file__))


def api_key():
    k = os.environ.get("RUNPOD_API_KEY")
    if not k:
        sys.exit("set RUNPOD_API_KEY (your Runpod API key)")
    return k


def endpoint_id():
    eid = ENDPOINT_ID
    if not eid:
        p = os.path.join(HERE, "serverless", "endpoint_id.txt")
        if os.path.exists(p):
            eid = open(p).read().strip()
    if not eid:
        sys.exit("set STEM_ENDPOINT or run serverless/deploy_serverless.py first")
    return eid


def base():
    return f"https://api.runpod.ai/v2/{endpoint_id()}"


def headers():
    return {"Authorization": f"Bearer {api_key()}"}


def run_job(payload, timeout=900, poll=1.0):
    r = requests.post(f"{base()}/run", headers=headers(), json={"input": payload}, timeout=60)
    r.raise_for_status()
    jid = r.json()["id"]
    t0 = time.time()
    last = None
    while True:
        s = requests.get(f"{base()}/status/{jid}", headers=headers(), timeout=60).json()
        last = s
        if s.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return s
        if time.time() - t0 > timeout:
            try:
                requests.post(f"{base()}/cancel/{jid}", headers=headers(), timeout=30)
            except Exception:
                pass
            raise TimeoutError(f"job {jid} not done after {timeout}s (last status {s.get('status')})")
        time.sleep(poll)


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def extract_audio(src, dest_wav):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-ac", "2",
         "-ar", "44100", "-c:a", "pcm_s16le", dest_wav],
        check=True,
    )


def is_probably_video(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
        return True
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return "video" in (r.stdout or "").lower()


def build_payload(src, fmt="flac"):
    if src.startswith(("http://", "https://")):
        return {"url": src, "format": fmt, "filename": os.path.basename(src.split("?")[0]) or "input"}
    if not os.path.exists(src):
        sys.exit(f"file not found: {src}")
    work_tmp = None
    path = src
    if is_probably_video(src):
        fd, work_tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        extract_audio(src, work_tmp)
        path = work_tmp
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {"audio_b64": b64, "filename": os.path.basename(path), "format": fmt}
    finally:
        if work_tmp:
            os.remove(work_tmp)


def save_stems(output, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    saved = {}
    for kind in ("vocals", "instrumental"):
        b64 = output.get(f"{kind}_b64")
        name = output.get(f"{kind}_filename") or f"{kind}.flac"
        if not b64:
            continue
        dest = os.path.join(out_dir, name)
        with open(dest, "wb") as f:
            f.write(base64.b64decode(b64))
        saved[kind] = dest
    return saved


def health():
    return requests.get(f"{base()}/health", headers=headers(), timeout=30).json()


def separate(src, fmt="flac", out_dir=None, timeout=900):
    t0 = time.time()
    payload = build_payload(src, fmt)
    # keep the returned JSON free of huge b64 when printing; still save files
    s = run_job(payload, timeout=timeout)
    rt = round(time.time() - t0, 2)
    rec = {
        "status": s.get("status"),
        "id": s.get("id"),
        "delay_ms": s.get("delayTime"),
        "exec_ms": s.get("executionTime"),
        "round_trip_s": rt,
        "output": None,
        "error": None,
        "saved": {},
    }
    if s.get("status") != "COMPLETED":
        rec["error"] = str(s.get("error") or s.get("output"))[:2000]
        return rec
    out = s.get("output") or {}
    rec["output"] = {k: v for k, v in out.items() if not str(k).endswith("_b64")}
    if out_dir and out.get("ok"):
        rec["saved"] = save_stems(out, out_dir)
    elif out.get("ok") is False or out.get("error"):
        rec["error"] = out.get("error")
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["health", "separate"])
    ap.add_argument("src", nargs="?")
    ap.add_argument("--format", default="flac", help="flac (default), wav, mp3, m4a, ogg")
    ap.add_argument("-o", "--out", help="directory to write vocals and instrumental files")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    t0 = time.time()
    if a.cmd == "health":
        print(json.dumps(health(), indent=2))
        sys.exit()
    if not a.src:
        sys.exit("separate needs a local file or a URL")
    rec = separate(a.src, a.format, a.out, a.timeout)
    print(json.dumps(rec, indent=2))
    print(f"round trip {time.time() - t0:.1f}s", file=sys.stderr)
    sys.exit(0 if rec.get("status") == "COMPLETED" and not rec.get("error") else 1)
