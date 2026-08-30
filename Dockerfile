FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# ComfyUI_LayerStyle (opencv-contrib-python) needs libGL at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Make sure ComfyUI core is on the latest stable release so the Qwen-Image-Edit-2511
# nodes used by this workflow (TextEncodeQwenImageEdit, TextEncodeQwenImageEditPlus,
# FluxKontextMultiReferenceLatentMethod, CFGNorm) are present.
RUN comfy --workspace /comfyui --skip-prompt update comfy --version latest

# Custom node: LayerUtility: ImageScaleByAspectRatio V2
# Skip the pinned "torch" line in its requirements.txt so we don't clobber the
# CUDA-matched torch build already in the base image.
RUN git clone --depth 1 https://github.com/chflame163/ComfyUI_LayerStyle.git \
      custom_nodes/ComfyUI_LayerStyle \
    && grep -v -i '^torch' custom_nodes/ComfyUI_LayerStyle/requirements.txt > /tmp/layerstyle-reqs.txt \
    && uv pip install -r /tmp/layerstyle-reqs.txt
