import os
import shutil
import subprocess

import runpod


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
    url = inp["url"]
    dest = inp["dest"]
    headers = inp.get("headers", {})
    # The Civitai key lives in the endpoint's env (set in the Runpod console),
    # so it never has to travel inside job payloads.
    if "civitai.com" in url and "Authorization" not in headers and os.environ.get("CIVITAI_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['CIVITAI_TOKEN']}"
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
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "size": size,
    }


runpod.serverless.start({"handler": handler})
