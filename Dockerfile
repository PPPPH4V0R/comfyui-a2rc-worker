FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# ComfyUI_LayerStyle (opencv-contrib-python) needs libGL at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# NOTE: we deliberately do NOT run `comfy update comfy` here. It reinstalls
# ComfyUI's requirements.txt, which contains a bare (unpinned) `torch` — that
# pulls PyPI's default (newest) CUDA wheel, which is even further ahead of
# what these hosts' drivers support than the problem fixed below. The
# 5.8.6-base tag (built 2026-06) already ships a recent enough ComfyUI core
# for the Qwen-Image-Edit-2511 nodes this workflow needs.
#
# Live-diagnosed: even the STOCK base image fails to start on the A100 SXM
# hosts available in this account's data center — torch there is pinned to a
# cu128 build (needs driver >=570), but these hosts report
# "found version 12060" (driver capped around CUDA 12.6, i.e. ~560.x).
# Re-pin torch/vision/audio to the cu126 wheel (same torch version, older
# CUDA build, needs only driver >=560) so it actually initializes here.
RUN uv pip install --python /opt/venv/bin/python --force-reinstall \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu126

# Custom node: LayerUtility: ImageScaleByAspectRatio V2
# Skip the pinned "torch" line in its requirements.txt so we don't clobber the
# CUDA-matched torch build already in the base image. Explicitly target
# /opt/venv here too — an unqualified `uv pip install` landed in the wrong
# place before (same class of bug as the comfy-cli fix above), which left
# ComfyUI's actual runtime venv without cv2 and the whole node silently
# failed to import ("ModuleNotFoundError: No module named 'cv2'").
RUN git clone --depth 1 https://github.com/chflame163/ComfyUI_LayerStyle.git \
      custom_nodes/ComfyUI_LayerStyle \
    && grep -v -i '^torch' custom_nodes/ComfyUI_LayerStyle/requirements.txt > /tmp/layerstyle-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/layerstyle-reqs.txt

# Custom nodes for the Krea2 workflows (all installs explicitly target
# /opt/venv per the fix above -- an unqualified `uv pip install` silently
# lands somewhere ComfyUI's actual runtime process never sees).

# GetImageSize+, SimpleMathDual+
RUN git clone --depth 1 https://github.com/cubiq/ComfyUI_essentials.git \
      custom_nodes/ComfyUI_essentials \
    && uv pip install --python /opt/venv/bin/python -r custom_nodes/ComfyUI_essentials/requirements.txt

# ColorMatchV2, DrawMaskOnImage
RUN git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git \
      custom_nodes/ComfyUI-KJNodes \
    && uv pip install --python /opt/venv/bin/python -r custom_nodes/ComfyUI-KJNodes/requirements.txt

# UltimateSDUpscale -- the actual upscale logic lives in a git submodule
RUN git clone --recurse-submodules --depth 1 https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git \
      custom_nodes/ComfyUI_UltimateSDUpscale

# Seed (rgthree), Label (rgthree) -- no requirements.txt, pure Python
RUN git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git \
      custom_nodes/rgthree-comfy

# Krea2EditGroundedEncode, Krea2EditModelPatch -- single-file node, no extra deps
RUN git clone --depth 1 https://github.com/lbouaraba/comfyui-krea2edit.git \
      custom_nodes/comfyui-krea2edit
