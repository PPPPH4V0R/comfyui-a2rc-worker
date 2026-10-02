import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

import runpod


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
