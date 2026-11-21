#!/usr/bin/env python3
"""Tiny Runpod GraphQL + REST v2 helper. Reads RUNPOD_API_KEY from env; never prints it."""
import os, sys, json, urllib.request, urllib.error

API = "https://api.runpod.io"

def _key():
    k = os.environ.get("RUNPOD_API_KEY")
    if not k:
        sys.exit("set RUNPOD_API_KEY")
    return k

def gql(query, variables=None):
    req = urllib.request.Request(
        f"{API}/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_key()}",
                 "User-Agent": "bs-roformer-stems-deploy"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:2000]}

def rest(method, path, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_key()}",
                 "User-Agent": "bs-roformer-stems-deploy"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return {"http": r.status, "data": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:4000]}

if __name__ == "__main__":
    print(json.dumps(gql(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()), indent=1))
