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

# Krea2EditGroundedEncode, Krea2EditModelPatch -- single-file node, no extra
# deps. Removed earlier this round of changes, re-added because the new "AIO
# Yuri" workflow's Mode-1 TE path uses this (older lbouaraba) implementation
# side by side with the newer ostris one below -- both are live in the same
# flattened graph (a Switch node picks between them at runtime).
RUN git clone --depth 1 https://github.com/lbouaraba/comfyui-krea2edit.git \
      custom_nodes/comfyui-krea2edit

# PathchSageAttentionKJ (sic -- that's the pack's real, typo'd class name) --
# same opencv-clobbering risk as other batches; filter it out.
RUN git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git \
      custom_nodes/ComfyUI-KJNodes \
    && grep -v -i '^opencv' custom_nodes/ComfyUI-KJNodes/requirements.txt > /tmp/kjnodes-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/kjnodes-reqs.txt

# Krea2ControlApply, Krea2ControlImageEncode, Krea2ControlLoRALoader -- no
# requirements.txt (404 on the repo)
RUN git clone --depth 1 https://github.com/facok/comfyui-krea2-controlnet.git \
      custom_nodes/comfyui-krea2-controlnet

# ImpactSwitch -- a ~15-line local shim (see shim-nodes/impact_switch_shim)
# reimplementing just this one node's behavior, instead of the full
# ComfyUI-Impact-Pack (which drags in segment-anything, scikit-image,
# transformers, and a git-built sam2 -- all unused; the AIO Yuri workflow
# only exercises Impact-Pack's trivial "pick input{N}" switch node).
COPY shim-nodes/impact_switch_shim custom_nodes/impact_switch_shim

# Context (rgthree), Context Big (rgthree), Power Lora Loader (rgthree),
# SetNode/GetNode -- the AIO Yuri workflow's "bus" pattern and Set/Get
# wiring depend on this pack extensively; live-diagnosed missing:
# "Node '采样器 context' not found ... class_type: Context (rgthree)".
# No requirements.txt (pure Python).
RUN git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git \
      custom_nodes/rgthree-comfy

# Switch any [Crystools] -- the AIO Yuri workflow's mode/ControlNet toggles
# route through this. Filter torch (same clobbering risk as every other
# pack here).
RUN git clone --depth 1 https://github.com/crystian/ComfyUI-Crystools.git \
      custom_nodes/ComfyUI-Crystools \
    && grep -v -i '^torch' custom_nodes/ComfyUI-Crystools/requirements.txt > /tmp/crystools-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/crystools-reqs.txt

# Int, String -- literal-value nodes, no extra deps. NOTE: drustan-hawk's
# "primitive-types" pack was tried first but registers lowercase "int"/
# "string" class_types, not a match; M1kep/ComfyLiterals registers exactly
# "Int" -> IntLiteral (param name "Number") and "String" -> StringLiteral
# (param name "String"), which is what this workflow's saved JSON actually
# uses -- confirmed live via "Node 'Mode 2 POS Prompt' not found" followed
# by matching IntLiteral's STRING-typed "Number" widget serialization
# ("1"/"2"/"3" as literal strings, not ints) in the source workflow.
RUN git clone --depth 1 https://github.com/M1kep/ComfyLiterals.git \
      custom_nodes/ComfyLiterals

# BooleanBasic -- no requirements.txt (404 on the repo)
RUN git clone --depth 1 https://github.com/gseth/ControlAltAI-Nodes.git \
      custom_nodes/ControlAltAI-Nodes

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

# Index TTS 2.5 nodes -- text-to-speech with zero-shot voice cloning, for the
# "配音" (dubbing) stage of the AI短剧 pipeline. Filter out its torch pin (same
# clobbering risk as every other pack here) and the git+https descript-
# audiotools line -- the requirements.txt lists it twice (once as a git+
# checkout, once pinned to 0.7.2 on PyPI); keep only the PyPI one, since both
# installing would just repeat the same package for no benefit and the git
# checkout is slower and less reproducible.
RUN git clone --depth 1 https://github.com/chenpipi0807/ComfyUI-Index-TTS.git \
      custom_nodes/ComfyUI-Index-TTS \
    && grep -v -i '^torch' custom_nodes/ComfyUI-Index-TTS/requirements.txt \
         | grep -v '^git+https://github.com/descriptinc/audiotools' \
         > /tmp/indextts-reqs.txt \
    && uv pip install --python /opt/venv/bin/python -r /tmp/indextts-reqs.txt

# This node package resolves its model directory as a hardcoded relative
# path (walking up 4 directories from its own file location to <ComfyUI>/
# models/IndexTTS-2.5), NOT through folder_paths.get_filename_list() like
# UNETLoader/CLIPLoader -- so it never sees the extra network-volume search
# path those get. Live-diagnosed: "IndexTTS-2.5 missing files in
# /comfyui/models/IndexTTS-2.5" even though the files are on the volume at
# /runpod-volume/models/IndexTTS-2.5. Bridge it with a symlink baked at
# build time -- /runpod-volume doesn't exist yet during the build, but a
# symlink only needs its target to resolve at ACCESS time, and the network
# volume is mounted there by the time any job runs.
RUN mkdir -p models && ln -sfn /runpod-volume/models/IndexTTS-2.5 models/IndexTTS-2.5

# worker-comfyui's handler.py (baked into the base image) only recognizes
# "images" node-output keys when building the job result -- confirmed by
# reading its source. SaveAudio's UI result is keyed "audio" instead (unlike
# SaveVideo, which happens to reuse "images" -- a different node's ui.as_dict()
# choice, not a version thing), so without this patch a TTS job would
# complete "successfully" in ComfyUI's own terms but return no audio at all.
# See patches/patch_handler_audio.py for the exact diff and reasoning.
COPY patches/patch_handler_audio.py /tmp/patch_handler_audio.py
RUN python3 /tmp/patch_handler_audio.py

# InstantCharacter (Tencent Hunyuan) -- whole-character (face + hairstyle +
# outfit) consistency for the "角色定型图集" tool, replacing the Krea2 AIO
# Yuri identity-edit path there: live testing showed Krea2's ref_boost-tuned
# identity edit still drifted on face/hair-color/accessories for real
# photos. InstantCharacter's node reads its FLUX/SigLIP/DINOv2/ip-adapter
# weights from plain string paths (InstantCharacterLoadModelFromLocal), not
# folder_paths, so the workflow just points those at the network volume's
# absolute paths directly -- no symlink dance needed like IndexTTS-2.5 above.
RUN git clone --depth 1 https://github.com/jax-explorer/ComfyUI-InstantCharacter.git \
      custom_nodes/ComfyUI-InstantCharacter \
    && uv pip install --python /opt/venv/bin/python -r custom_nodes/ComfyUI-InstantCharacter/requirements.txt

# Live-diagnosed: ComfyUI's own node loader reported "InstantCharacterLoadModelFromLocal
# not found" at RUNTIME, meaning the package's imports raised somewhere during
# ComfyUI's custom_nodes loading -- but this endpoint's worker logs only expose
# "system" (container lifecycle) events, never "container" (stdout/stderr), so
# there's no way to see the actual traceback from a live worker. Reproduce the
# exact import chain at BUILD time instead, via a small script file (avoids
# shell-quoting a multi-line python -c string): a failure here fails the
# build and prints the traceback straight into the GitHub Actions log, which
# we CAN read, unlike the runtime worker logs.
COPY patches/check_instantcharacter_import.py custom_nodes/ComfyUI-InstantCharacter/check_import.py
RUN cd custom_nodes/ComfyUI-InstantCharacter && /opt/venv/bin/python check_import.py
