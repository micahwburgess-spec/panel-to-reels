"""Find the camera shots inside each clip's spans and the face positions in each shot.

Usage: shots.py P CLIP [CLIP...]
  -> P/shots.json             {"A": [{"span": 0, "n": 1, "start": s, "end": e, "faces": [[x, y, w, h], ...]}]}
  -> P/sheets/shots_<CLIP>.jpg one ruled mid-shot frame per shot (yellow ruler .1 to .9 across the
                              16:9 frame, cyan ticks under detected faces, label "CLIP #n start-end")
  and prints each shot's face x centers so you can fill "framing" in clips.json:
     {"from": <shot start>, "x": <speaker face x>, "crop": 0.62}
Cut detection is dissolve-aware: 4 fps 96x54 gray frames, each compared with the frame 0.5s
earlier; a mean difference above 9 marks a cut (a dissolve shows up as one run of high values).
"""
import json, os, shutil, subprocess, sys
import numpy as np
import common, hlg
from PIL import Image, ImageDraw

DFPS, DW, DH = 4, 96, 54
LAG = 2            # frames: 0.5s apart at 4 fps
THRESH = 9
SHEET_W = 960


def span_bounds(W, a, b):
    """Same cut points build.py uses for a word span."""
    s = W[a]["s"] - 0.12
    e = W[b]["e"] + 0.22
    if b + 1 < len(W): e = min(e, W[b + 1]["s"] - 0.02)
    return max(0.0, s), e


def detect_cuts(src, s, e):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(s), "-t", str(e - s), "-i", src,
                          "-vf", f"fps={DFPS},scale={DW}:{DH},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, DH, DW).astype(np.float32)
    if len(fr) <= LAG: return []
    diff = np.abs(fr[LAG:] - fr[:-LAG]).mean(axis=(1, 2))        # diff[n] compares frame n+LAG with frame n
    hot = diff > THRESH
    cuts, n = [], 0
    while n < len(hot):
        if hot[n]:
            m = n
            while m + 1 < len(hot) and hot[m + 1]: m += 1
            k = n + int(np.argmax(diff[n:m + 1]))
            cuts.append(round(s + (k + LAG / 2) / DFPS, 2))       # middle of the compared pair
            n = m + 1
        else:
            n += 1
    return [refine(src, c) for c in cuts if s + 0.5 < c < e - 0.5]


def refine(src, c):
    """Snap a coarse cut time to the biggest frame-to-frame jump within +-0.5s (midway between the two frames)."""
    num, _, den = common.probe(src, "stream=r_frame_rate").partition("/")
    fps = float(num) / float(den or 1)
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(c - 0.5), "-t", "1", "-i", src,
                          "-vf", f"scale={DW}:{DH},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, DH, DW).astype(np.float32)
    if len(fr) < 2: return c
    j = int(np.argmax(np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))))
    return round(c - 0.5 + (j + 0.5) / fps, 3)


def ruled(img, faces):
    d = ImageDraw.Draw(img)
    w, h = img.size
    fnt = common.font("Poppins-SemiBold.ttf", 18)
    for k in range(1, 10):
        x = w * k / 10
        d.line([x, 0, x, 16], fill=(255, 220, 0), width=2)
        d.line([x, h - 16, x, h], fill=(255, 220, 0), width=2)
        d.text((x + 3, 16), f".{k}", font=fnt, fill=(255, 220, 0), stroke_width=2, stroke_fill=(0, 0, 0))
    for f in faces:
        x, y, fw, fh = f
        cx, by = x * w, (y + fh / 2) * h
        d.polygon([(cx, by + 4), (cx - 9, by + 20), (cx + 9, by + 20)], fill=(0, 230, 255))
        d.text((cx - 18, by + 22), f"{x:.2f}", font=fnt, fill=(0, 230, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    return img


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    P = common.project(sys.argv[1])
    src = common.source_video(P)
    W = common.load_words(P)
    sw, sh = common.dims(src)
    path = os.path.join(P, "shots.json")
    allshots = json.load(open(path)) if os.path.exists(path) else {}
    for k in sys.argv[2:]:
        c = common.clip(P, k)
        if c.get("source_file"):
            print(f"{k}: has source_file, no shots to find"); continue
        tmp = os.path.join(common.workdir(P, "frames"), f"shots_{k}")
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        shots = []
        for si, (a, b) in enumerate(c["spans"]):
            s, e = span_bounds(W, a, b)
            bounds = [s] + detect_cuts(src, s, e) + [e]
            for p, q in zip(bounds, bounds[1:]):
                shots.append({"span": si, "n": len(shots) + 1, "start": round(p, 2), "end": round(q, 2)})
        # mid frame of each shot at 1920 wide (same scale build.py tracks at) for the face detector
        for sh_ in shots:
            mid = (sh_["start"] + sh_["end"]) / 2
            hlg.frame(src, mid, 1920, int(round(1920 * sh / sw / 2)) * 2).save(f"{tmp}/{sh_['n']:03d}.jpg", quality=92)
        common.run([common.tool("faces"), tmp, f"{tmp}/faces.json"], stdout=subprocess.DEVNULL)
        F = json.load(open(f"{tmp}/faces.json"))
        for sh_ in shots:
            faces = sorted((f for f in F.get(f"{sh_['n']:03d}.jpg", []) if f[3] > 0.012), key=lambda f: f[0])
            sh_["faces"] = [[round(v, 3) for v in f] for f in faces]
        # contact sheet
        th = int(round(SHEET_W * sh / sw))
        cols = 2 if len(shots) > 1 else 1
        rows = (len(shots) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * SHEET_W, rows * (th + 40)), (16, 16, 18))
        d = ImageDraw.Draw(sheet)
        lf = common.font("Poppins-SemiBold.ttf", 24)
        for i, sh_ in enumerate(shots):
            x, y = (i % cols) * SHEET_W, (i // cols) * (th + 40)
            im = Image.open(f"{tmp}/{sh_['n']:03d}.jpg").resize((SHEET_W, th))
            sheet.paste(ruled(im, sh_["faces"]), (x, y + 40))
            d.text((x + 10, y + 6), f"{k} #{sh_['n']}  {sh_['start']:.2f}-{sh_['end']:.2f}", font=lf, fill=(255, 255, 255))
        out = os.path.join(common.workdir(P, "sheets"), f"shots_{k}.jpg")
        sheet.save(out, quality=88)
        allshots[k] = shots
        print(f"\n{k}: {len(shots)} shot(s)   sheet: {out}")
        for sh_ in shots:
            xs = "  ".join(f"{f[0]:.2f}" + ("" if f[3] > 0.05 else "(small)") for f in sh_["faces"]) or "no faces (wide/cutaway: letterbox?)"
            print(f"  #{sh_['n']:<2} {sh_['start']:8.2f} - {sh_['end']:8.2f}  ({sh_['end'] - sh_['start']:5.1f}s)  face x: {xs}")
        print("  framing template (set x to the speaker's face, left to right as listed):")
        print("  " + json.dumps([{"from": 0 if i == 0 else sh_["start"], "x": None, "crop": 0.62} for i, sh_ in enumerate(shots)]))
    json.dump(allshots, open(path, "w"), indent=1)


if __name__ == "__main__":
    main()
