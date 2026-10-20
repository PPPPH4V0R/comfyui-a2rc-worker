"""Runpod Serverless handler: Japanese audio -> Chinese subtitles (srt/vtt/lrc).

A job payload is capped at 10 MB, so the page sends the file in pieces first:
  {"action": "put_chunk", "upload_id": "...", "index": 0, "data": "<base64>"}
then asks for the subtitles:
  {"action": "transcribe", "upload_id": "...", "filename": "x.mp3", "vad_threshold": 0.4}
Pieces are kept on the network volume and deleted once transcribed (or after a day if abandoned).
"""
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import time

import runpod

UPLOADS = "/runpod-volume/asmr_uploads"
HISTORY_DIR = "/runpod-volume/outputs"  # shared with the ComfyUI worker; the history page lists it
UPLOAD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SUFFIXES = "mp3,wav,flac,m4a,aac,ogg,opus,wma,mp4,mkv,avi,mov,webm,flv,wmv"


def clean_stale(max_age_s=86400):
    for d in glob.glob(os.path.join(UPLOADS, "*")):
        try:
            if time.time() - os.path.getmtime(d) > max_age_s:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def transcribe(folder, inp):
    name = re.sub(r"[^\w.\- ]", "_", os.path.basename(inp.get("filename") or "audio.mp3"))[-80:]
    if "." not in name:
        name += ".mp3"
    parts = sorted(glob.glob(os.path.join(folder, "part_*")))
    if not parts:
        return {"error": "没有收到上传的文件"}
    work = os.path.join(folder, "work")
    os.makedirs(work, exist_ok=True)
    src = os.path.join(work, name)
    with open(src, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)

    cmd = ["python3", "infer.py", "--device", "cuda", "--overwrite", "--log_level", "INFO",
           "--audio_suffixes", SUFFIXES, "--sub_formats", "srt,vtt,lrc"]
    if inp.get("vad_threshold") is not None:
        cmd += ["--vad_threshold", str(float(inp["vad_threshold"]))]
    start = time.time()
    r = subprocess.run(cmd + [src], cwd="/app/fw", capture_output=True, text=True, timeout=3 * 3600)
    stem = os.path.splitext(src)[0]
    subs = {}
    for fmt in ("srt", "vtt", "lrc"):
        if os.path.exists(f"{stem}.{fmt}"):
            with open(f"{stem}.{fmt}", encoding="utf-8") as f:
                subs[fmt] = f.read()
    log = (r.stdout + r.stderr)[-3000:]
    if not subs:
        return {"error": "没生成字幕", "log": log}
    return {"subtitles": subs, "seconds": round(time.time() - start)}


def save_history(job_id, name, subs):
    """Keep the subtitles next to the image history so a closed page can still find them."""
    try:
        folder = os.path.join(HISTORY_DIR, time.strftime("%Y-%m-%d", time.gmtime()), re.sub(r"[^A-Za-z0-9_-]", "", job_id))
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(name)[0]
        files = []
        for fmt, text in subs.items():
            data = text.encode("utf-8")
            with open(os.path.join(folder, f"{stem}.{fmt}"), "wb") as f:
                f.write(data)
            files.append({"name": f"{stem}.{fmt}", "size": len(data), "thumb": None})
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"id": job_id, "time": time.time(), "label": "asmr", "files": files}, f, ensure_ascii=False)
    except Exception as e:
        print("saving subtitles to history failed:", e)


def handler(job):
    inp = job["input"]
    uid = str(inp.get("upload_id", ""))
    if not UPLOAD_ID.match(uid):
        return {"error": "upload_id 不对"}
    folder = os.path.join(UPLOADS, uid)

    if inp.get("action") == "put_chunk":
        os.makedirs(folder, exist_ok=True)
        index = int(inp["index"])
        with open(os.path.join(folder, f"part_{index:05d}"), "wb") as f:
            f.write(base64.b64decode(inp["data"]))
        return {"ok": True, "index": index}

    if inp.get("action") == "transcribe":
        clean_stale()
        try:
            out = transcribe(folder, inp)
            if out.get("subtitles"):
                save_history(job.get("id") or uid, inp.get("filename") or "audio", out["subtitles"])
            return out
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return {"error": "未知的 action"}


runpod.serverless.start({"handler": handler})
