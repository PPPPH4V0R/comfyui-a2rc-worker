# comfyui-a2rc-worker

Custom `runpod/worker-comfyui` image for the "动漫转写实真人" (Qwen-Image-Edit-2511 + LayerStyle)
workflow. Adds the [ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle)
custom node on top of the official base image and updates ComfyUI core to latest stable.

Models are **not** baked into this image — they're expected on a Runpod Network Volume
mounted at `/runpod-volume/models/...`. Push to `main` (or run the workflow manually)
to build and publish `ghcr.io/<owner>/comfyui-a2rc:v1`.
