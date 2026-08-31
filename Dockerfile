FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# ComfyUI_LayerStyle (opencv-contrib-python) needs libGL at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# NOTE: we deliberately do NOT run `comfy update comfy` here. It reinstalls
# ComfyUI's requirements.txt, which contains a bare (unpinned) `torch` — that
# pulls PyPI's default CUDA-13 wheel and clobbers the base image's carefully
# pinned CUDA-12.8 torch build, which then fails to initialize on these hosts'
# drivers ("NVIDIA driver ... too old (found version 12060)"). The 5.8.6-base
# tag (built 2026-06) already ships a recent enough ComfyUI core for the
# Qwen-Image-Edit-2511 nodes this workflow needs — verified at deploy time via
# a smoke test rather than blindly upgrading.

# Custom node: LayerUtility: ImageScaleByAspectRatio V2
# Skip the pinned "torch" line in its requirements.txt so we don't clobber the
# CUDA-matched torch build already in the base image.
RUN git clone --depth 1 https://github.com/chflame163/ComfyUI_LayerStyle.git \
      custom_nodes/ComfyUI_LayerStyle \
    && grep -v -i '^torch' custom_nodes/ComfyUI_LayerStyle/requirements.txt > /tmp/layerstyle-reqs.txt \
    && uv pip install -r /tmp/layerstyle-reqs.txt
