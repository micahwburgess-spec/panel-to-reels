"""Stage 1: cut + vertical-reframe each clip from the long source video.

Usage: build.py P [CLIP...]          (no clips = every clip in clips.json)

Per clip, from clips.json:
  spans    word-index ranges (inclusive) from transcript.json: exact cut points on word boundaries
  fix      word index -> replacement caption text ("" removes the word from the captions)
  framing  per-shot speaker hint: {"from": source seconds, "x": face center 0..1 in the 16:9 frame,
           "crop": crop height as a fraction of source height}, or {"from": t, "mode": "letterbox"}
           for wide/reaction shots
Output: P/base/<clip>.mp4 (1080x1920, graded, loudness-normalized) + P/base/<clip>.words.json
Clips with "source_file" are skipped (they are already edited; see transcribe.py --file).
"""
import json, os, shutil, subprocess, sys
import numpy as np
import common
from common import run

FPS = common.FPS
GRADE = "eq=contrast=1.06:saturation=1.05:gamma=0.97,vignette=angle=0.45"


class Build:
    def __init__(self, P):
        self.P = P
        self.src = common.source_video(P)
        self.SW, self.SH = common.dims(self.src)
        self.W = common.load_words(P)
        self.out = common.workdir(P, "base")
        self.frames = common.workdir(P, "frames")

    def pieces_for(self, c):
        """Split each word span at framing boundaries -> list of (s, e, framing)."""
        W, out = self.W, []
        marks = sorted(c.get("framing") or [], key=lambda f: f["from"])
        if not marks:
            common.die("clip has no framing: run shots.py and add framing marks to clips.json")
        for a, b in c["spans"]:
            s = max(0.0, W[a]["s"] - 0.12)
            e = W[b]["e"] + 0.22
            if b + 1 < len(W): e = min(e, W[b + 1]["s"] - 0.02)
            cuts = sorted({s, e} | {f["from"] for f in marks if s + 0.3 < f["from"] < e - 0.3})
            for p, q in zip(cuts, cuts[1:]):
                fr = ([f for f in marks if f["from"] <= p + 1e-3] or marks[:1])[-1]
                out.append((round(p, 3), round(q, 3), fr))
        return out

    def track(self, k, i, s, e, fr):
        """Face-track the hinted speaker; returns per-frame (t, x, y) crop centers."""
        d = os.path.join(self.frames, f"{k}{i}")
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(s), "-t", str(e - s), "-i", self.src,
             "-vf", "fps=4,scale=1920:-2", "-q:v", "3", f"{d}/%04d.jpg"])
        run([common.tool("faces"), d, f"{d}/faces.json"], stdout=subprocess.DEVNULL)
        F = json.load(open(f"{d}/faces.json"))
        xs, ys, ts = [], [], []
        cx, cy = fr["x"], None
        for n, name in enumerate(sorted(F)):
            cand = [f for f in F[name] if abs(f[0] - cx) < 0.14 and f[3] > 0.012]
            if cand:
                f = min(cand, key=lambda f: abs(f[0] - cx))
                cx = 0.7 * cx + 0.3 * f[0]           # follow, but resist jumping to a neighbor
                cy = f[1] if cy is None else 0.7 * cy + 0.3 * f[1]
            ts.append(n / 4.0); xs.append(cx); ys.append(cy)
        if not ts: ts, xs, ys = [0.0], [fr["x"]], [None]
        if all(y is None for y in ys): ys = [0.32] * len(ys)
        ys = [y if y is not None else next(v for v in ys if v is not None) for y in ys]

        def smooth(v):   # gaussian, sigma ~0.6s at 4 fps
            v = np.array(v, float)
            if len(v) < 3: return v
            k_ = np.exp(-0.5 * (np.arange(-6, 7) / 2.4) ** 2); k_ /= k_.sum()
            return np.convolve(np.pad(v, 6, mode="edge"), k_, mode="valid")
        xs, ys = smooth(xs), smooth(ys)
        n = int(round((e - s) * FPS))
        t = np.arange(n) / FPS
        fx = np.interp(t, ts, xs) if len(ts) > 1 else np.full(n, xs[0])
        fy = np.interp(t, ts, ys) if len(ts) > 1 else np.full(n, ys[0])
        return t, fx, fy

    def zoom_schedule(self, s, e):
        """Jump-zoom: punch in/out on sentence starts, at most every ~4s."""
        W = self.W
        last, cur, sched = s, 1.0, []
        for j, w in enumerate(W):
            if j and s + 1.5 < w["s"] < e - 1.0 and w["s"] - last > 4.0:
                if W[j - 1]["w"].endswith((".", "?", "!")):
                    cur = 0.84 if cur == 1.0 else 1.0
                    sched.append((w["s"] - s - 0.05, cur)); last = w["s"]
        return sched

    def render_piece(self, k, i, s, e, fr, path):
        SW, SH = self.SW, self.SH
        inp = ["-ss", str(s), "-t", str(e - s), "-i", self.src]
        afade = f"afade=t=in:d=0.02,afade=t=out:st={max(0, e - s - 0.03):.3f}:d=0.03"
        enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        if fr.get("mode") == "letterbox":
            vf = (f"[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                  f"boxblur=30:2,eq=brightness=-0.12[bg];[b]scale=1080:-2,{GRADE}[fg];"
                  f"[bg][fg]overlay=0:(H-h)/2-80,setsar=1[v];[0:a]{afade}[a2]")
            run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inp,
                 "-filter_complex", vf, "-map", "[v]", "-map", "[a2]", *enc, path])
            return
        crop = fr.get("crop", 0.62)
        t, fx, fy = self.track(k, i, s, e, fr)
        zs = self.zoom_schedule(s, e)
        cmds, prev, first = [], None, None
        for j, tt in enumerate(t):
            z = 1.0
            for ts_, zz in zs:
                if tt >= ts_: z = zz
            ch = int(SH * crop * z) // 2 * 2
            cw = int(ch * 9 / 16) // 2 * 2
            x = int(np.clip(fx[j] * SW - cw / 2, 0, SW - cw)) // 2 * 2
            y = int(np.clip(fy[j] * SH - ch * 0.34, 0, SH - ch)) // 2 * 2   # face sits ~34% down
            box = (x, y, cw, ch)
            if box != prev:
                cmds.append(f"{tt:.4f} crop w {cw}, crop h {ch}, crop x {x}, crop y {y};")
                prev = box
                first = first or box
        cmdfile = os.path.basename(path) + ".cmd"
        open(os.path.join(self.out, cmdfile), "w").write("\n".join(cmds))
        x0, y0, w0, h0 = first
        vf = (f"[0:v]sendcmd=f='{cmdfile}',crop=w={w0}:h={h0}:x={x0}:y={y0}:exact=1,"
              f"scale=1080:1920:flags=lanczos,{GRADE},setsar=1[v];[0:a]{afade}[a2]")
        # run inside base/ so the sendcmd path needs no filtergraph escaping
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", *inp,
             "-filter_complex", vf, "-map", "[v]", "-map", "[a2]", *enc, path], cwd=self.out)

    def build(self, k, c):
        pcs = self.pieces_for(c)
        files, words, off = [], [], 0.0
        fix = c.get("fix") or {}
        keep = {i for a, b in c["spans"] for i in range(a, b + 1)}
        for i, (s, e, fr) in enumerate(pcs):
            p = os.path.join(self.out, f"{k}_p{i}.mp4")
            self.render_piece(k, i, s, e, fr, p)
            files.append(p)
            for wi, w in enumerate(self.W):
                if wi in keep and s <= w["s"] < e:
                    text = fix.get(str(wi), w["w"])
                    if text == "": continue                    # "" removes the word from the captions
                    words.append({"i": wi, "w": text, "s": round(w["s"] - s + off, 3),
                                  "e": round(min(w["e"], e) - s + off, 3)})
            off += e - s
        lst = os.path.join(self.out, f"{k}.list")
        open(lst, "w").write("".join(f"file '{os.path.basename(f)}'\n" for f in files))
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
             os.path.join(self.out, f"{k}.mp4")])
        json.dump(words, open(os.path.join(self.out, f"{k}.words.json"), "w"), indent=0)
        print(k, f"{off:.1f}s", len(pcs), "pieces", len(words), "words", flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    P = common.project(sys.argv[1])
    clips = common.load_clips(P)
    b = Build(P)
    for k in (sys.argv[2:] or clips):
        if k not in clips: common.die(f"clip {k!r} not in clips.json")
        if clips[k].get("source_file"):
            print(k, "has source_file: nothing to build"); continue
        b.build(k, clips[k])


if __name__ == "__main__":
    main()
