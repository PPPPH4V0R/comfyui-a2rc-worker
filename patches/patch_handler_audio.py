"""
Patches the baked-in worker-comfyui handler.py (at /handler.py) to also
return SaveAudio-type node outputs.

Unlike SaveVideo/PreviewVideo (which happens to reuse the "images" UI key,
so the stock handler already returns video files for free -- see the
git log for that discovery), ComfyUI core's SaveAudio node wraps its result
as ui.SavedAudios, whose as_dict() returns {"audio": [...]} -- a genuinely
different key the stock handler has no branch for, so TTS output would be
silently dropped without this patch. This mirrors the existing images-
handling block almost line for line (same /view fetch, same base64
encoding), just keyed on "audio" and appended to the same output_data list
so the frontend's existing "images[0]" result path needs no changes.
"""

HANDLER_PATH = "/handler.py"

with open(HANDLER_PATH, "r", encoding="utf-8") as f:
    src = f.read()

anchor = '''                    else:
                        error_msg = f"Failed to fetch image data for {filename} from /view endpoint."
                        errors.append(error_msg)

            # Check for other output types'''

audio_block = '''                    else:
                        error_msg = f"Failed to fetch image data for {filename} from /view endpoint."
                        errors.append(error_msg)

            if "audio" in node_output:
                print(
                    f"worker-comfyui - Node {node_id} contains {len(node_output['audio'])} audio file(s)"
                )
                for audio_info in node_output["audio"]:
                    filename = audio_info.get("filename")
                    subfolder = audio_info.get("subfolder", "")
                    audio_type = audio_info.get("type")

                    if audio_type == "temp":
                        print(
                            f"worker-comfyui - Skipping audio {filename} because type is 'temp'"
                        )
                        continue

                    if not filename:
                        warn_msg = f"Skipping audio in node {node_id} due to missing filename: {audio_info}"
                        print(f"worker-comfyui - {warn_msg}")
                        errors.append(warn_msg)
                        continue

                    audio_bytes = get_image_data(filename, subfolder, audio_type)

                    if audio_bytes:
                        try:
                            base64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                            output_data.append(
                                {
                                    "filename": filename,
                                    "type": "base64",
                                    "data": base64_audio,
                                }
                            )
                            print(f"worker-comfyui - Encoded {filename} as base64")
                        except Exception as e:
                            error_msg = f"Error encoding {filename} to base64: {e}"
                            print(f"worker-comfyui - {error_msg}")
                            errors.append(error_msg)
                    else:
                        error_msg = f"Failed to fetch audio data for {filename} from /view endpoint."
                        errors.append(error_msg)

            # Check for other output types'''

assert src.count(anchor) == 1, f"expected exactly one match for the images-block anchor, found {src.count(anchor)}"
src = src.replace(anchor, audio_block, 1)

other_keys_anchor = '            other_keys = [k for k in node_output.keys() if k != "images"]'
other_keys_new = '            other_keys = [k for k in node_output.keys() if k not in ("images", "audio")]'
assert src.count(other_keys_anchor) == 1, f"expected exactly one match for the other_keys anchor, found {src.count(other_keys_anchor)}"
src = src.replace(other_keys_anchor, other_keys_new, 1)

with open(HANDLER_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("handler.py patched: audio outputs now returned alongside images.")
