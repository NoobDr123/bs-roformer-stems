#!/usr/bin/env python3
"""Change the stems endpoint worker limits. Usage: python3 set_workers.py MIN MAX [IDLE_TIMEOUT_S]
MAX=0 disables the endpoint completely (no workers at all)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rp import rest
HERE = os.path.dirname(os.path.abspath(__file__))
eid = os.environ.get("STEM_ENDPOINT") or open(os.path.join(HERE, "endpoint_id.txt")).read().strip()
mn, mx = int(sys.argv[1]), int(sys.argv[2])
idle = int(sys.argv[3]) if len(sys.argv) > 3 else 180
body = {"workers": {"min": mn, "max": mx, "idleTimeout": idle}}
r = rest("PATCH", f"/v2/serverless/{eid}", body)
print(json.dumps(r, indent=2)[:4000])
