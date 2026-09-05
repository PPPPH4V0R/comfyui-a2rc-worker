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

# `comfy update comfy` only pulls ComfyUI's git-managed CODE into /comfyui; it
# does not touch the PACKAGE dependencies already installed in /opt/venv (the
# actual launch venv start.sh uses). The newer code ends up calling into
# newer APIs of packages still at their old base-image versions. Live-
# diagnosed crash: core's attention.py now calls
# `comfy_kitchen.int8_attention_is_available()`, which the base image's older
# comfy_kitchen doesn't have -> ComfyUI's main.py dies on import, surfacing
# only as "ComfyUI server not reachable" with no indication why. Re-sync
# every dependency in the *new* requirements.txt into /opt/venv so nothing is
# left on a stale version relative to the code that now imports it.
#
# NOTE: this step runs BEFORE the torch re-pin below, deliberately. Excluding
# the literal "torch" line here is not enough -- some other package in this
# same requirements.txt apparently *constrains* torch to a newer version than
# 2.11.0, so `--upgrade` on the full set silently drags torch along with it
# (back to a default/cu13 wheel) even with torch itself filtered out. Rather
# than chase every transitive constraint, just let this step land wherever it
# lands and force the correct torch build again immediately after.
RUN uv pip install --python /opt/venv/bin/python --upgrade -r requirements.txt

# `comfy update comfy`'s requirements.txt contains a bare (unpinned) `torch`,
# and (per the note above) the sync step just before this one can also pull
# in a newer torch transitively via some other package's constraint -- both
# resolve to PyPI's default (newest) CUDA wheel. Live-diagnosed: the A100 SXM
# hosts in this account's data center report "found version 12060" (driver
# capped around CUDA 12.6, i.e. ~560.x), well short of what a default (CUDA
# 13) torch build needs. Re-pin torch/vision/audio to the cu126 wheel (same
# torch version, older CUDA build, needs only driver >=560) as the LAST word
# on torch -- nothing after this line may touch it again.
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

# Custom nodes (all installs explicitly target /opt/venv per the fix above --
# an unqualified `uv pip install` silently lands somewhere ComfyUI's actual
# runtime process never sees).
#
# The 5 packs previously installed here for the first Krea2 batch
# (ComfyUI_essentials, ComfyUI-KJNodes, ComfyUI_UltimateSDUpscale,
# rgthree-comfy, comfyui-krea2edit) were removed: none of their node types
# are used by the workflows still deployed after that batch was retired in
# favor of the single "Krea2 Ostris Edit + SeedVR2 + Z-Image" pipeline below.

# Krea2OstrisEditModelPatch, TextEncodeKrea2OstrisEdit -- no extra deps
RUN git clone --depth 1 https://github.com/ostris/ComfyUI-Krea2-Ostris-Edit.git \
      custom_nodes/ComfyUI-Krea2-Ostris-Edit

# easy loraStack, easy loraStackApply, easy cleanGpuUsed (ComfyUI-Easy-Use)
RUN git clone --depth 1 https://github.com/yolain/ComfyUI-Easy-Use.git \
      custom_nodes/ComfyUI-Easy-Use \
    && uv pip install --python /opt/venv/bin/python -r custom_nodes/ComfyUI-Easy-Use/requirements.txt

# JjkText -- no requirements.txt, pure Python
RUN git clone --depth 1 https://github.com/jjkramhoeft/ComfyUI-Jjk-Nodes.git \
      custom_nodes/ComfyUI-Jjk-Nodes

# FlowMatchEulerDiscreteScheduler (Custom) -- no extra deps
RUN git clone --depth 1 https://github.com/erosDiffusion/ComfyUI-EulerDiscreteScheduler.git \
      custom_nodes/ComfyUI-EulerDiscreteScheduler

# Image Filter Adjustments -- only this one node out of WAS Node Suite's ~210
# is used, but the class name is registered by the whole pack. Same
# opencv-clobbering risk as the previous batch's packs; filter it out.
RUN git clone --depth 1 https://github.com/WASasquatch/was-node-suite-comfyui.git \
      custom_nodes/was-node-suite-comfyui \
    && grep -v -i '^opencv' custom_nodes/was-node-suite-comfyui/requirements.txt > /tmp/was-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/was-reqs.txt

# RES4LYF -- not used for any of its own sampler nodes here, only for its
# import-time side effect of appending "beta57" (and others) to comfy's
# global SCHEDULER_NAMES list, which is what makes "beta57" selectable as a
# plain KSampler scheduler value (the workflow's node 7 needs exactly that;
# live-diagnosed: "scheduler: 'beta57' not in [...]" without this pack).
RUN git clone --depth 1 https://github.com/ClownsharkBatwing/RES4LYF.git \
      custom_nodes/RES4LYF \
    && grep -v -i '^opencv' custom_nodes/RES4LYF/requirements.txt > /tmp/res4lyf-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/res4lyf-reqs.txt

# The opencv-exclusion filter above only catches requirements.txt TOP-LEVEL
# lines; transitive deps can still silently overwrite LayerStyle's
# opencv-contrib-python build regardless of filtering. Reinstall contrib as
# the final, unconditional word after every other node pack's deps have
# landed, so it's never the one left overwritten.
RUN uv pip install --python /opt/venv/bin/python --force-reinstall opencv-contrib-python
