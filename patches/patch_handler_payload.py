"""
Patches the baked-in worker-comfyui handler.py (at /handler.py) so big
multi-image results still reach the caller.

Runpod rejects a job result over ~20 MB: the worker logs "Failed to return
job results. | 400, message='Bad Request', url=.../job-done/..." and the job
never completes. Workflow 16 saves eight 1248x1824 PNGs (~23 MB, ~31 MB as
base64), so every default run hit it. When the base64 total is over the
budget, PNG outputs are re-encoded as JPEG (lowering quality until it fits);
videos/audio and small results are left untouched.
"""

HANDLER_PATH = "/handler.py"

with open(HANDLER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

helper = '''
RESULT_BUDGET = int(os.environ.get("RESULT_BUDGET_BYTES", 15_000_000))
_STREAM_JOB = False  # set per job by stream_handler (patch_handler_stream.py)


def _fit_result_budget(items):
    """Re-encode PNG outputs as JPEG when the base64 payload is too big for Runpod."""
    def total():
        return sum(len(it.get("data", "")) for it in items if it.get("type") == "base64")

    # Streamed jobs send one image per message, so each stays far below the limit.
    if _STREAM_JOB or total() <= RESULT_BUDGET:
        return items
    from PIL import Image

    pngs = [it for it in items if it.get("type") == "base64" and it.get("filename", "").lower().endswith(".png")]
    originals = {id(it): base64.b64decode(it["data"]) for it in pngs}
    for quality in (92, 85, 75, 60):
        for it in pngs:
            img = Image.open(BytesIO(originals[id(it)])).convert("RGB")
            buf = BytesIO()
            img.save(buf, "JPEG", quality=quality)
            it["data"] = base64.b64encode(buf.getvalue()).decode("utf-8")
            if it["filename"].lower().endswith(".png"):
                it["filename"] = it["filename"][:-4] + ".jpg"
        print(f"worker-comfyui - Result too large; PNGs re-encoded as JPEG q={quality}, base64 total {total()} bytes")
        if total() <= RESULT_BUDGET:
            break
    return items


def handler(job):'''

anchor = "\ndef handler(job):"
assert src.count(anchor) == 1, f"expected exactly one handler definition, found {src.count(anchor)}"
src = src.replace(anchor, helper, 1)

result_anchor = '''    if output_data:
        final_result["images"] = output_data'''
assert src.count(result_anchor) == 1, f"expected exactly one match for the result anchor, found {src.count(result_anchor)}"
src = src.replace(result_anchor, '''    if output_data:
        output_data = _fit_result_budget(output_data)
        final_result["images"] = output_data''', 1)

with open(HANDLER_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("handler.py patched: oversized PNG results are re-encoded as JPEG.")
