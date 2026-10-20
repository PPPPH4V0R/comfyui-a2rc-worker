"""
Patches the baked-in worker-comfyui handler.py (at /handler.py) so every
job's output files are also sent to the owner's Telegram chat.

A Runpod job result only lives ~30 minutes after it completes and the web
pages are the only thing that fetches it, so closing the tab used to lose the
images. With TELEGRAM_BOT_TOKEN (a Runpod secret) and TELEGRAM_CHAT_ID set on
the endpoint, each output is sent to that chat with sendDocument (documents
keep the original file; photos would be recompressed). Nothing is kept on the
server. Without those variables this does nothing. Sending never fails the job.

Must run after patch_handler_payload.py and patch_handler_stream.py: it hooks
the start of _fit_result_budget (before any JPEG re-encode, so originals are
sent) and records the job's label in stream_handler.
"""

HANDLER_PATH = "/handler.py"

with open(HANDLER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

assert "def stream_handler(job):" in src, "apply patch_handler_stream.py first"

helper = '''
_TELEGRAM_CTX = {}
TELEGRAM_LABELS = {"wf16": "16 号工作流", "qwen_edit": "Qwen 编辑", "krea2_ostris": "Krea2 编辑",
                   "krea2_aio_yuri": "Krea2 AIO", "wan22_i2v": "图生视频"}


def _send_telegram(items):
    """Send this job's base64 outputs to the owner's Telegram chat (best effort)."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    label = _TELEGRAM_CTX.get("label") or ""
    caption = (TELEGRAM_LABELS.get(label, label) + " · " if label else "") + time.strftime("%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600))
    sent = 0
    for it in items:
        if it.get("type") != "base64" or not it.get("data"):
            continue
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": chat, "caption": caption},
                              files={"document": (it.get("filename") or "output.png", base64.b64decode(it["data"]))},
                              timeout=120)
            sent += r.ok
            if not r.ok:
                print(f"worker-comfyui - Telegram refused {it.get('filename')}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"worker-comfyui - Sending {it.get('filename')} to Telegram failed: {e}")
    print(f"worker-comfyui - Sent {sent} output(s) to Telegram")


def _fit_result_budget(items):'''

anchor = "\ndef _fit_result_budget(items):"
assert src.count(anchor) == 1, f"expected one _fit_result_budget, found {src.count(anchor)}"
src = src.replace(anchor, helper, 1)

body_anchor = '''    """Re-encode PNG outputs as JPEG when the base64 payload is too big for Runpod."""
'''
assert src.count(body_anchor) == 1
src = src.replace(body_anchor, body_anchor + "    _send_telegram(items)\n", 1)

ctx_anchor = '''def stream_handler(job):
    global _STREAM_JOB
'''
assert src.count(ctx_anchor) == 1
src = src.replace(ctx_anchor, ctx_anchor + '''    _TELEGRAM_CTX.clear()
    _TELEGRAM_CTX.update(label=(job.get("input") or {}).get("history_label"))
''', 1)

for mod in ("time", "base64", "requests"):
    assert f"import {mod}" in src, f"handler no longer imports {mod}"

with open(HANDLER_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("handler.py patched: job outputs are also sent to Telegram when configured.")
