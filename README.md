# BS-RoFormer stem splitter on Runpod Serverless

Splits vocals and instrumental from an ad (audio or video) with
`python-audio-separator` and the BS-RoFormer Viperx 1297 vocals model
(`model_bs_roformer_ep_317_sdr_12.9755.ckpt`).

The endpoint scales to zero (min workers 0). Idle timeout is 180 s. FlashBoot is on.
Nothing running = $0/h.

## Usage

```bash
export RUNPOD_API_KEY=...
python3 client.py health
python3 client.py separate test/test_ad.mp4 -o test/out_cold
python3 client.py separate test/test_ad.mp4 -o test/out_warm
```

Auth is your Runpod API key. The client writes `vocals.flac` and `instrumental.flac`
(or `.mp3` if you pass `--format mp3`) into the `-o` directory.

## Files

- `handler.py` — Runpod worker (loads the baked model at boot)
- `client.py` — local client
- `serverless/deploy_serverless.py` — create the endpoint
- `serverless/set_workers.py` — change min/max workers / idle timeout
- `Dockerfile` — CUDA 12.4 image with the weights baked in
