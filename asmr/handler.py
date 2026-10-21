"""Runpod Serverless handler: Japanese audio -> Chinese subtitles (srt/vtt/lrc).

A job payload is capped at 10 MB, so the page sends the file in pieces first:
  {"action": "put_chunk", "upload_id": "...", "index": 0, "data": "<base64>"}
then asks for the subtitles:
  {"action": "transcribe", "upload_id": "...", "filename": "x.mp3", "vad_threshold": 0.4}
Pieces are kept on the network volume and deleted once transcribed (or after a day if abandoned).
"""
import base64
import glob
import os
import re
import shutil
import subprocess
import time

import requests
import runpod

UPLOADS = "/runpod-volume/asmr_uploads"
UPLOAD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SUFFIXES = "mp3,wav,flac,m4a,aac,ogg,opus,wma,mp4,mkv,avi,mov,webm,flv,wmv"


def clean_stale(max_age_s=86400):
    for d in glob.glob(os.path.join(UPLOADS, "*")):
        try:
            if time.time() - os.path.getmtime(d) > max_age_s:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


MODEL_DIR = "/runpod-volume/models/asmr_chickenrice"
HF = "https://huggingface.co/"
MODEL_FILES = {  # path under MODEL_DIR -> source (the layout infer.py expects in ./models)
    **{f: HF + "chickenrice0721/whisper-large-v2-translate-zh-v0.2-st-ct2/resolve/main/" + f
       for f in ("model.bin", "config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")},
    "whisper_vad.onnx": HF + "TransWithAI/Whisper-Vad-EncDec-ASMR-onnx/resolve/main/model.onnx",
    "whisper_vad_metadata.json": HF + "TransWithAI/Whisper-Vad-EncDec-ASMR-onnx/resolve/main/model_metadata.json",
    **{"whisper-base/" + f: HF + "openai/whisper-base/resolve/main/" + f
       for f in ("preprocessor_config.json", "config.json", "tokenizer.json", "vocab.json")},
}


def ensure_models():
    """Fetch the models onto the volume the first time a worker in a new data center needs them."""
    for rel, url in MODEL_FILES.items():
        dest = os.path.join(MODEL_DIR, rel)
        if os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = f"{dest}.part{os.getpid()}"
        print("downloading", rel, flush=True)
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for block in r.iter_content(8 << 20):
                    f.write(block)
        os.replace(part, dest)  # atomic, so a half-written file is never taken for a finished one


def transcribe(folder, inp):
    ensure_models()
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


def send_telegram(name, subs, note=""):
    """Send the .lrc (what the user plays along with) to the owner's Telegram chat when configured."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    fmt = "lrc" if subs.get("lrc") else "srt"
    if not token or not chat or not subs.get(fmt):
        return
    try:
        stem = os.path.splitext(name)[0]
        note = (note or "").strip()[:800]
        caption = (note + "\n" if note else "") + f"ASMR 翻译 · {name}"
        requests.post(f"https://api.telegram.org/bot{token}/sendDocument", data={"chat_id": chat, "caption": caption},
                      files={"document": (f"{stem}.{fmt}", subs[fmt].encode("utf-8"))}, timeout=60)
    except Exception as e:
        print("sending subtitles to Telegram failed:", e)


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
                send_telegram(inp.get("filename") or "audio", out["subtitles"], inp.get("note"))
            return out
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return {"error": "未知的 action"}


runpod.serverless.start({"handler": handler})
