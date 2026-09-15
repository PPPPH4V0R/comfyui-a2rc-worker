"""
Build-time smoke test for ComfyUI-InstantCharacter's import chain.

Mirrors what ComfyUI's custom_nodes loader does at runtime -- namespace-
package imports for InstantCharacter.pipeline and nodes.comfy_nodes -- so a
failure here fails the Docker build with the real traceback in the GitHub
Actions log, instead of silently registering zero nodes at runtime (which is
all we could observe live: "InstantCharacterLoadModelFromLocal not found").
"""
import sys

sys.path.insert(0, ".")

from InstantCharacter.pipeline import InstantCharacterFluxPipeline  # noqa: F401

print("InstantCharacter.pipeline OK")

from nodes.comfy_nodes import InstantCharacterLoadModelFromLocal  # noqa: F401

print("nodes.comfy_nodes OK")
