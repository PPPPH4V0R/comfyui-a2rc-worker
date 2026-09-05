FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# ComfyUI_LayerStyle (opencv-contrib-python) needs libGL at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The Krea2 workflows need a ComfyUI core new enough to offer "krea2" as a
# CLIPLoader type (the 5.8.6-base tag, built 2026-06, predates it — confirmed
# live: "type: 'krea2' not in (list of length 23)"). Update to latest, via an
# upgraded comfy-cli (the base's pinned 1.13.0 predates the
# "update comfy --version" flag; see the earlier live-diagnosis).
RUN uv pip install --python /opt/venv/bin/python --upgrade comfy-cli \
    && comfy --workspace /comfyui --skip-prompt update comfy --version latest

# `comfy update comfy` reinstalls ComfyUI's requirements.txt, which contains
# a bare (unpinned) `torch` — that pulls PyPI's default (newest) CUDA wheel.
# Live-diagnosed: the A100 SXM hosts in this account's data center report
# "found version 12060" (driver capped around CUDA 12.6, i.e. ~560.x), well
# short of what a default (CUDA 13) torch build needs. Re-pin torch/vision/
# audio to the cu126 wheel (same torch version, older CUDA build, needs only
# driver >=560) AFTER the update above, so this is the last word on torch.
RUN uv pip install --python /opt/venv/bin/python --force-reinstall \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu126

# `comfy update comfy` only pulls ComfyUI's git-managed CODE into /comfyui; it
# does not touch the PACKAGE dependencies already installed in /opt/venv (the
# actual launch venv start.sh uses). The newer code ends up calling into
# newer APIs of packages still at their old base-image versions. Live-
# diagnosed crash: core's attention.py now calls
# `comfy_kitchen.int8_attention_is_available()`, which the base image's older
# comfy_kitchen doesn't have -> ComfyUI's main.py dies on import, surfacing
# only as "ComfyUI server not reachable" with no indication why. Re-sync
# every dependency in the *new* requirements.txt into /opt/venv (excluding
# torch/vision/audio, already pinned correctly above) so nothing is left on
# a stale version relative to the code that now imports it.
RUN grep -v -iE '^(torch|torchvision|torchaudio)([=<> ]|$)' requirements.txt > /tmp/comfyui-reqs.txt \
    && uv pip install --python /opt/venv/bin/python --upgrade -r /tmp/comfyui-reqs.txt

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
# Its requirements.txt pulls "rembg"/"transparent-background", which drag in
# plain opencv-python-headless -- installing that AFTER LayerStyle's
# opencv-contrib-python replaces cv2 with a build missing ximgproc (breaks
# LayerStyle's guidedFilter-based functions). Filter it out; LayerStyle
# already provides a full-featured cv2 for everyone to share.
RUN git clone --depth 1 https://github.com/cubiq/ComfyUI_essentials.git \
      custom_nodes/ComfyUI_essentials \
    && grep -v -i '^opencv' custom_nodes/ComfyUI_essentials/requirements.txt > /tmp/essentials-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/essentials-reqs.txt

# ColorMatchV2, DrawMaskOnImage -- same opencv-clobbering issue as above.
RUN git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git \
      custom_nodes/ComfyUI-KJNodes \
    && grep -v -i '^opencv' custom_nodes/ComfyUI-KJNodes/requirements.txt > /tmp/kjnodes-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/kjnodes-reqs.txt

# UltimateSDUpscale -- the actual upscale logic lives in a git submodule
RUN git clone --recurse-submodules --depth 1 https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git \
      custom_nodes/ComfyUI_UltimateSDUpscale

# Seed (rgthree), Label (rgthree) -- no requirements.txt, pure Python
RUN git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git \
      custom_nodes/rgthree-comfy

# Krea2EditGroundedEncode, Krea2EditModelPatch -- single-file node, no extra deps
RUN git clone --depth 1 https://github.com/lbouaraba/comfyui-krea2edit.git \
      custom_nodes/comfyui-krea2edit

# The opencv-exclusion filters above only catch requirements.txt TOP-LEVEL
# lines; transitive deps (e.g. essentials' "rembg" pulls in plain
# opencv-python/-headless on its own) still silently overwrite LayerStyle's
# opencv-contrib-python build regardless of filtering. Reinstall contrib as
# the final, unconditional word after every other node pack's deps have
# landed, so it's never the one left overwritten.
RUN uv pip install --python /opt/venv/bin/python --force-reinstall opencv-contrib-python
