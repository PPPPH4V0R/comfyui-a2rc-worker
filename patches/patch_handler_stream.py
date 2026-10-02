"""
Patches the baked-in worker-comfyui handler.py (at /handler.py) so a job can
get its images back one message per image, at full PNG quality.

A job result is capped at ~20 MB and each stream message at 1 MB, but there is
no cap on the number of messages. Jobs whose input has "stream_images": true
get every image as consecutive stream messages
({"index", "total", "filename", "type", "part", "parts", "data"}: concatenate
the parts' data), followed by {"done": true, ...}; the caller reads them from
/stream/<job id>. Other jobs behave as before,
except that a generator handler's /status output is a one-element list
([result]) -- the pages unwrap it.

Must run after patch_handler_payload.py (it uses _STREAM_JOB from there).
"""

HANDLER_PATH = "/handler.py"

with open(HANDLER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

assert "_STREAM_JOB = False" in src, "apply patch_handler_payload.py first"

wrapper = '''
# Same dict object the SDK keeps; return_aggregate_stream is read on every
# yield, so it can be chosen per job (workers run one job at a time).
_START_CONFIG = {"return_aggregate_stream": True}
# Each stream message is capped at 1 MB, so an image's base64 goes out in parts.
STREAM_PART_CHARS = 700_000


def stream_handler(job):
    global _STREAM_JOB
    _STREAM_JOB = bool((job.get("input") or {}).get("stream_images"))
    try:
        result = handler(job)
    finally:
        stream, _STREAM_JOB = _STREAM_JOB, False
    images = result.get("images") if isinstance(result, dict) else None
    if not (stream and images) or result.get("error"):
        _START_CONFIG["return_aggregate_stream"] = True
        yield result
        return
    _START_CONFIG["return_aggregate_stream"] = False
    for i, img in enumerate(images):
        data = img.get("data", "")
        parts = max(1, -(-len(data) // STREAM_PART_CHARS))
        for p in range(parts):
            yield {"index": i, "total": len(images), "filename": img.get("filename"), "type": img.get("type"),
                   "part": p, "parts": parts, "data": data[p * STREAM_PART_CHARS:(p + 1) * STREAM_PART_CHARS]}
    yield {"done": True, "total": len(images), "errors": result.get("errors", [])}


if __name__ == "__main__":'''

anchor = '\nif __name__ == "__main__":'
assert src.count(anchor) == 1, f"expected one __main__ block, found {src.count(anchor)}"
src = src.replace(anchor, wrapper, 1)

start_anchor = '    runpod.serverless.start({"handler": handler})'
assert src.count(start_anchor) == 1, f"expected one start() call, found {src.count(start_anchor)}"
src = src.replace(start_anchor, '''    _START_CONFIG["handler"] = stream_handler
    runpod.serverless.start(_START_CONFIG)''', 1)

with open(HANDLER_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("handler.py patched: stream_images jobs return one image per stream message.")
