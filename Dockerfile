# BS-RoFormer vocals stem splitter for Runpod Serverless.
# Weights are baked in so a cold worker does not download the model.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODEL_DIR=/models \
    MODEL_FILENAME=model_bs_roformer_ep_317_sdr_12.9755.ckpt \
    MODEL_YAML=model_bs_roformer_ep_317_sdr_12.9755.yaml

# build-essential is only needed to compile the diffq wheel, then removed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip python3.11-dev \
        build-essential \
        ffmpeg libsndfile1 wget ca-certificates \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
    && python3.11 -m pip install --no-cache-dir --upgrade pip \
    && python3.11 -m pip install --no-cache-dir \
        torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124 \
    && printf 'torch==2.5.1\ntorchaudio==2.5.1\n' > /tmp/constraints.txt \
    && python3.11 -m pip install --no-cache-dir -c /tmp/constraints.txt \
        audio-separator runpod requests soundfile \
    && apt-get purge -y --auto-remove build-essential python3.11-dev \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip /tmp/constraints.txt

# Official Viperx 1297 BS-RoFormer vocals weights (SDR 12.9755) + yaml config.
RUN mkdir -p /models \
 && wget -q -O /models/${MODEL_FILENAME} \
        https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/${MODEL_FILENAME} \
 && wget -q -O /models/${MODEL_YAML} \
        https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/${MODEL_YAML} \
 && python3.11 -c "import os; p=os.path.join('/models', os.environ['MODEL_FILENAME']); assert os.path.getsize(p)>500_000_000, p"

WORKDIR /app
COPY handler.py /app/handler.py
CMD ["python3.11", "-u", "/app/handler.py"]
