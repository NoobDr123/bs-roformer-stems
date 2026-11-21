#!/usr/bin/env python3
"""Create the BS-RoFormer stems serverless endpoint on Runpod (API v2).

Needs RUNPOD_API_KEY. Uses the already-pushed image IMAGE (override with env).
Does not touch the Shot Reader endpoint.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rp import rest

IMAGE = os.environ.get("STEM_IMAGE", "ghcr.io/noobdr123/bs-roformer-stems:latest")
NAME = os.environ.get("STEM_NAME", "bs-roformer-stems -fb")
# Speed first: 4090 pool, then 5090, then L40S/6000 Ada. Do not include the
# AMPERE_24 pool (L4 / 3090) — slower cards in a cheaper pool.
POOLS = os.environ.get("STEM_POOLS", "ADA_24,ADA_32_PRO,ADA_48_PRO").split(",")
WORKERS_MAX = int(os.environ.get("STEM_WORKERS_MAX", "2"))
IDLE = int(os.environ.get("STEM_IDLE_TIMEOUT", "180"))

body = {
    "name": NAME,
    "image": IMAGE,
    "type": "QUEUE",
    "flashboot": "FLASHBOOT",
    "gpu": {"pools": POOLS, "count": 1},
    "workers": {"min": 0, "max": WORKERS_MAX, "idleTimeout": IDLE},
    "scaling": {"type": "QUEUE_DELAY", "queueDelay": 4},
    "disk": int(os.environ.get("STEM_DISK_GB", "30")),
    "timeout": int(os.environ.get("STEM_TIMEOUT_MS", "900000")),  # 15 min, covers a cold image pull
}

print("creating endpoint", json.dumps({k: v for k, v in body.items()}, indent=2))
r = rest("POST", "/v2/serverless", body)
print(json.dumps(r, indent=2)[:8000])
data = r.get("data") or {}
eid = data.get("id") or (data.get("endpoint") or {}).get("id")
if eid:
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endpoint_id.txt")
    open(out, "w").write(eid + "\n")
    print("endpoint id written to", out)
else:
    sys.exit("create failed")
