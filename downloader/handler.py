import base64
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

import runpod

HISTORY_DIR = "/runpod-volume/outputs"


def normalize_url(url):
    """Turn the links people copy from their browser into direct download links.

    Civitai mirror domains (civitai.red etc.) don't accept the API key, and model pages
    aren't downloads; Hugging Face "blob" pages are HTML, "resolve" is the file.
    """
    u = urllib.parse.urlparse(url.strip())
    host = u.hostname or ""
    if "civitai" in host:
        q = urllib.parse.parse_qs(u.query)
        if u.path.startswith("/api/download/models/"):
            return urllib.parse.urlunparse(("https", "civitai.com", u.path, "", u.query, ""))
        if "modelVersionId" in q:
            return f"https://civitai.com/api/download/models/{q['modelVersionId'][0]}"
        m = re.match(r"/models/(\d+)", u.path)
        if m:  # model page without a version: take the newest version
            req = urllib.request.Request(f"https://civitai.com/api/v1/models/{m.group(1)}", headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return f"https://civitai.com/api/download/models/{json.load(r)['modelVersions'][0]['id']}"
    if host.endswith("huggingface.co") and "/blob/" in u.path:
        return url.replace("/blob/", "/resolve/", 1)
    return url


def handler(job):
    inp = job["input"]
    action = inp.get("action", "download")

    if action == "list":
        path = inp["path"]
        try:
            return {"entries": sorted(os.listdir(path))}
        except Exception as e:
            return {"error": str(e)}

    if action == "move":
        os.makedirs(os.path.dirname(inp["dst"]), exist_ok=True)
        shutil.move(inp["src"], inp["dst"])
        return {"ok": True}

    if action == "mkdir":
        os.makedirs(inp["path"], exist_ok=True)
        return {"ok": True}

    if action == "rm":
        os.remove(inp["path"])
        return {"ok": True}

    if action == "stat":
        path = inp["path"]
        exists = os.path.exists(path)
        return {"exists": exists, "size": os.path.getsize(path) if exists else 0}

    if action == "du":
        # The volume sits on shared storage, so disk_usage() reports the whole
        # cluster; sum the files ourselves to see this volume's own usage.
        root = inp.get("path", "/runpod-volume")
        per_dir, total = {}, 0
        for dirpath, _dirs, files in os.walk(root):
            size = sum(os.path.getsize(os.path.join(dirpath, f)) for f in files
                       if not os.path.islink(os.path.join(dirpath, f)))
            total += size
            top = os.path.relpath(dirpath, root).split(os.sep)[:2]
            key = "/".join(top)
            per_dir[key] = per_dir.get(key, 0) + size
        return {"total": total, "per_dir": per_dir}

    if action == "tree":
        # Model file names under each folder, relative to it; the web pages use this
        # to offer what is actually on the volume without being republished.
        root = "/runpod-volume/models"
        out = {}
        for folder in inp.get("folders", ["loras", "checkpoints", "diffusion_models", "unet"]):
            base = os.path.join(root, os.path.normpath(folder).lstrip("./"))
            names = []
            for dirpath, _dirs, files in os.walk(base, followlinks=True):
                for f in files:
                    if f.endswith((".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft")):
                        names.append(os.path.relpath(os.path.join(dirpath, f), base).replace(os.sep, "/"))
            out[folder] = sorted(names)
        return out

    if action == "history_list":
        # Recent jobs saved by the ComfyUI worker (patch_handler_history.py), newest first,
        # with their thumbnails inline so the history page needs one call to draw.
        jobs = []
        for meta_path in glob.glob(os.path.join(HISTORY_DIR, "*", "*", "meta.json")):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            folder = os.path.dirname(meta_path)
            meta["dir"] = os.path.relpath(folder, HISTORY_DIR).replace(os.sep, "/")
            for item in meta.get("files", []):
                thumb = item.get("thumb") and os.path.join(folder, item["thumb"])
                if thumb and os.path.exists(thumb):
                    with open(thumb, "rb") as f:
                        item["thumb_data"] = base64.b64encode(f.read()).decode()
            jobs.append(meta)
        jobs.sort(key=lambda m: m.get("time", 0), reverse=True)
        return {"jobs": jobs[: int(inp.get("limit", 40))]}

    if action == "read_file":
        # One piece of a saved output file (pieces keep each job result under Runpod's size cap).
        path = os.path.realpath(os.path.join(HISTORY_DIR, inp["path"]))
        if not path.startswith(os.path.realpath(HISTORY_DIR) + os.sep) or not os.path.isfile(path):
            return {"error": "file not found"}
        offset, length = int(inp.get("offset", 0)), min(int(inp.get("length", 8_000_000)), 8_000_000)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(length)
        return {"data": base64.b64encode(data).decode(), "size": size, "eof": offset + len(data) >= size}

    if action == "diskfree":
        total, used, free = shutil.disk_usage(inp.get("path", "/runpod-volume"))
        return {"total": total, "used": used, "free": free}

    # default: download a URL straight onto the network volume
    url = normalize_url(inp["url"])
    dest = inp["dest"]
    headers = inp.get("headers", {})
    # Site keys live in the endpoint's env (set in the Runpod console),
    # so they never have to travel inside job payloads.
    host = urllib.parse.urlparse(url).hostname or ""
    if host.endswith("civitai.com") and "Authorization" not in headers and os.environ.get("CIVITAI_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['CIVITAI_TOKEN']}"
    if host.endswith("huggingface.co") and "Authorization" not in headers and os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = ["curl", "-L", "-o", dest, "--fail", "--retry", "3", "--connect-timeout", "30"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=inp.get("timeout", 3300))
    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    if result.returncode != 0 and os.path.exists(dest):
        # don't leave a truncated file behind under the real filename
        os.remove(dest)
    hints = {401: "网站要求登录：Civitai 的 key 失效了，或者 HuggingFace 的仓库需要申请访问 / HF_TOKEN。",
             403: "作者限制了下载（或需要先在网站上点同意条款），换个来源。",
             404: "链接不对，文件不存在。"}
    code = re.search(r"returned error: (\d+)", result.stderr or "")
    return {
        "url": url,
        "hint": hints.get(int(code.group(1)), "") if code else "",
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "size": size,
    }


runpod.serverless.start({"handler": handler})
