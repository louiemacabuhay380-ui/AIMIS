"""
Saves the MediaPipe files used for behavior analysis (eye contact, expression, gestures)
into static/mediapipe/, so the interview page works without an internet connection.

Run it once from the project folder (with the venv active):
    python download_mediapipe.py
"""
import os
import urllib.request

VERSION = "0.10.14"
LIB = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{VERSION}"
MODELS = "https://storage.googleapis.com/mediapipe-models"

FILES = {
    "vision_bundle.mjs": f"{LIB}/vision_bundle.mjs",
    "wasm/vision_wasm_internal.js": f"{LIB}/wasm/vision_wasm_internal.js",
    "wasm/vision_wasm_internal.wasm": f"{LIB}/wasm/vision_wasm_internal.wasm",
    "wasm/vision_wasm_nosimd_internal.js": f"{LIB}/wasm/vision_wasm_nosimd_internal.js",
    "wasm/vision_wasm_nosimd_internal.wasm": f"{LIB}/wasm/vision_wasm_nosimd_internal.wasm",
    "models/face_landmarker.task": f"{MODELS}/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "models/hand_landmarker.task": f"{MODELS}/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
}

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "mediapipe")
failed = []
for name, url in FILES.items():
    path = os.path.join(base, *name.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        print(f"Downloading {name} ...", end=" ", flush=True)
        urllib.request.urlretrieve(url, path)
        print(f"{os.path.getsize(path) / 1_000_000:.1f} MB")
    except Exception as e:
        print("FAILED:", e)
        failed.append(name)

if failed:
    print("\nSome files failed. Check your internet connection and run this again.")
else:
    print(f"\nDone. All files are in {base}")
    print("The interview page will now use these files instead of the internet.")
