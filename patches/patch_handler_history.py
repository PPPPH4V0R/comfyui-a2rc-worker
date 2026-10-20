"""
Patches the baked-in worker-comfyui handler.py (at /handler.py) so every
job's output files are also kept on the network volume for 7 days.

A Runpod job result only lives ~30 minutes after it completes, and the web
pages are the only thing that fetches it: close the tab (or reboot) and the
images are gone. Now each job's outputs land in
/runpod-volume/outputs/<YYYY-MM-DD>/<job id>/ with small JPEG thumbnails and
a meta.json ({id, time, label, files}); the model-downloader endpoint's
history_list / read_file actions serve them to the history page. Folders older
than HISTORY_DAYS are deleted whenever a new job saves.

Must run after patch_handler_payload.py and patch_handler_stream.py: it hooks
the start of _fit_result_budget (before any JPEG re-encode, so originals are
kept) and records the job id / label in stream_handler.
"""

HANDLER_PATH = "/handler.py"

with open(HANDLER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

assert "def stream_handler(job):" in src, "apply patch_handler_stream.py first"

helper = '''
HISTORY_DIR = "/runpod-volume/outputs"
HISTORY_DAYS = int(os.environ.get("HISTORY_DAYS", 7))
_HISTORY_CTX = {}


def _save_history(items):
    """Copy this job's base64 outputs to the volume (best effort: never fails the job)."""
    import glob
    import re
    import shutil
    try:
        if not os.path.isdir("/runpod-volume"):
            return
        from PIL import Image
        job_id = re.sub(r"[^A-Za-z0-9_-]", "", str(_HISTORY_CTX.get("id") or "")) or uuid.uuid4().hex
        today = time.strftime("%Y-%m-%d", time.gmtime())
        folder = os.path.join(HISTORY_DIR, today, job_id)
        os.makedirs(folder, exist_ok=True)
        files = []
        for i, it in enumerate(items):
            if it.get("type") != "base64" or not it.get("data"):
                continue
            name = f"{i:02d}_" + re.sub(r"[^\\w.\\-]", "_", os.path.basename(it.get("filename") or f"output{i}.png"))
            raw = base64.b64decode(it["data"])
            with open(os.path.join(folder, name), "wb") as f:
                f.write(raw)
            thumb = None
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                im = Image.open(BytesIO(raw)).convert("RGB")
                im.thumbnail((320, 320))
                thumb = name.rsplit(".", 1)[0] + ".thumb.jpg"
                im.save(os.path.join(folder, thumb), "JPEG", quality=75)
            files.append({"name": name, "size": len(raw), "thumb": thumb})
        meta = {"id": job_id, "time": time.time(), "label": _HISTORY_CTX.get("label") or "", "files": files}
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - HISTORY_DAYS * 86400))
        for day in glob.glob(os.path.join(HISTORY_DIR, "*")):
            if os.path.basename(day) < cutoff:
                shutil.rmtree(day, ignore_errors=True)
        print(f"worker-comfyui - Saved {len(files)} output(s) to {folder}")
    except Exception as e:
        print(f"worker-comfyui - Saving outputs to history failed: {e}")


def _fit_result_budget(items):'''

anchor = "\ndef _fit_result_budget(items):"
assert src.count(anchor) == 1, f"expected one _fit_result_budget, found {src.count(anchor)}"
src = src.replace(anchor, helper, 1)

body_anchor = '''    """Re-encode PNG outputs as JPEG when the base64 payload is too big for Runpod."""
'''
assert src.count(body_anchor) == 1
src = src.replace(body_anchor, body_anchor + "    _save_history(items)\n", 1)

ctx_anchor = '''def stream_handler(job):
    global _STREAM_JOB
'''
assert src.count(ctx_anchor) == 1
src = src.replace(ctx_anchor, ctx_anchor + '''    _HISTORY_CTX.clear()
    _HISTORY_CTX.update(id=job.get("id"), label=(job.get("input") or {}).get("history_label"))
''', 1)

for mod in ("json", "time", "uuid", "base64"):
    assert f"import {mod}" in src, f"handler no longer imports {mod}"

with open(HANDLER_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("handler.py patched: job outputs are also kept on the volume for the history page.")
