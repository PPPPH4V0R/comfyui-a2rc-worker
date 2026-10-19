# Japanese -> Chinese ASMR subtitles on Runpod Serverless.
# Runs TransWithAI's Faster-Whisper-TransWithAI-ChickenRice (MIT) unchanged; its
# "海南鸡 v2" CTranslate2 model, ASMR VAD and whisper-base feature extractor live
# on the network volume (models/asmr_chickenrice), so the image stays small.
# CUDA 12.4: the US-WA-1 hosts (where the network volume lives) run drivers that cap at 12.6.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PIP_BREAK_SYSTEM_PACKAGES=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip git ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG FW_COMMIT=62104884d8553be1c30bc88c157d82b2b8d0792b
RUN git clone https://github.com/TransWithAI/Faster-Whisper-TransWithAI-ChickenRice.git /app/fw \
    && git -C /app/fw checkout "$FW_COMMIT"

# transformers is only used for WhisperFeatureExtractor (numpy), so no torch is needed.
RUN pip install --no-cache-dir runpod "ctranslate2>=4.5.0" "faster-whisper>=1.0.0" "transformers>=4.30.0" \
      pyjson5 librosa onnxruntime requests

# infer.py chdirs to its own folder and loads ./models
RUN ln -s /runpod-volume/models/asmr_chickenrice /app/fw/models

COPY handler.py /app/handler.py
CMD ["python3", "-u", "/app/handler.py"]
