"""Grab a still from a video as an SDR (sRGB) PIL image, tone-mapping iPhone HLG HDR properly."""
import subprocess
import numpy as np
from PIL import Image

M709_2020 = np.array([[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0114], [0.0164, 0.0880, 0.8956]])
M2020_709 = np.linalg.inv(M709_2020)
A, B, C = 0.17883277, 0.28466892, 0.55991073
REF = 0.30        # slightly above BT.2408 white so bright walls hold detail in the SDR still


def is_hlg(src):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=color_transfer", "-of", "csv=p=0", src]).decode()
    return "arib-std-b67" in out


def frame(src, t, w=1080, h=1920):
    if not is_hlg(src):
        raw = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1",
                                       "-vf", f"scale={w}:{h},format=rgb24", "-f", "rawvideo", "-"])
        return Image.frombytes("RGB", (w, h), raw)
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1",
                                   "-vf", f"scale={w}:{h}:in_color_matrix=bt2020:in_range=tv:out_range=pc,format=rgb48le",
                                   "-f", "rawvideo", "-"])
    s = np.frombuffer(raw, "<u2").reshape(h, w, 3).astype(np.float64) / 65535
    e = np.where(s <= 0.5, s * s / 3, (np.exp((s - C) / A) + B) / 12)        # inverse HLG OETF -> scene light
    lin = e / REF                                                           # reference white -> 1.0
    with np.errstate(all="ignore"):
        lin = np.clip(lin @ M2020_709.T, 0, None)                               # BT.2020 -> BT.709 primaries
    k = 0.8                                                                  # soft shoulder for highlights
    lin = np.where(lin <= k, lin, k + (1 - k) * np.tanh((lin - k) / (1 - k)))
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8))
