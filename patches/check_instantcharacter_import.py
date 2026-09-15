"""
Diagnostic for ComfyUI-InstantCharacter's import chain -- run via `docker run`
against the freshly built image from .github/workflows/build.yml (posted to
the Actions step summary), not at build time. Mirrors what ComfyUI's
custom_nodes loader does at runtime: namespace-package imports for
InstantCharacter.pipeline and nodes.comfy_nodes. Live-diagnosed failure:
ComfyUI silently registered zero nodes from this package
("InstantCharacterLoadModelFromLocal not found") with no way to see why --
this endpoint's worker logs never expose container stdout/stderr, and this
repo's Actions raw logs require a GitHub login to view.

Uses an absolute path (not cwd-relative) since this may run via
`docker run --entrypoint` from an arbitrary working directory.
"""
import sys
import traceback

sys.path.insert(0, "/comfyui/custom_nodes/ComfyUI-InstantCharacter")

try:
    from InstantCharacter.pipeline import InstantCharacterFluxPipeline  # noqa: F401

    print("InstantCharacter.pipeline OK")
except Exception:
    traceback.print_exc()

try:
    from nodes.comfy_nodes import InstantCharacterLoadModelFromLocal  # noqa: F401

    print("nodes.comfy_nodes OK")
except Exception:
    traceback.print_exc()
