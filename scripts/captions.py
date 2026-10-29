"""Stage 2: burn build-up word-by-word captions onto P/base/<clip>.(mp4|mov).

Usage: captions.py P CLIP STYLE        -> P/out/<CLIP>_<STYLE>.mp4

Styles come from P/styles.json (or the skill's styles.json). The "caption" block of a style:
  font / size             normal words, e.g. "Poppins-SemiBold.ttf" 54, or "Sora:SemiBold" 50 (variable font)
  emph_font / emph_size   emphasis words (bigger, colored)
  colors                  [[r,g,b], ...] solid highlight + emphasis color, cycling per page
  gradient                [[r,g,b], ...] left-to-right gradient fill instead of solid colors
  pill                    [r,g,b,a] dark pill drawn behind pages over bright backgrounds
  text                    [r,g,b] color of words that are not lit (default white)
  plate                   {"fill": [r,g,b], "text": [r,g,b]}: emphasis words sit on a solid plate instead of
                          being colored (a logo-style label); "pad" sets its horizontal padding in px
  upper                   true to set captions in caps
A style may also carry a top-level "grade": an ffmpeg filter chain applied to the video under the captions
(and to the cover still), e.g. "hue=s=0,curves=..." for a black and white look. The base clip is unchanged.
Words pop in as spoken; the spoken word lights up; every page gets at least one emphasis word
(clips.json "emphasis" indices first, auto-picked otherwise). iPhone HLG HDR input stays 10-bit HLG.
Clip keys used: fix, emphasis, caption_center (px from top, default 1215; ~1430 for selfie framing).
"""
import json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import common

W, H, FPS = common.W, common.H, common.FPS
STRIP_H = 520                          # caption band height; the block is centered 215px into it
CENTER = 215
DEFAULT_CENTER = 1215                  # 63% down the frame
MAX_W = 880
STRIP_Y = DEFAULT_CENTER - CENTER
PAD = 0                                # extra space each side of an emphasis word (set from the style's plate)


def adv(w, f, ef):
    """Horizontal space a word takes on its line."""
    return ef.getlength(w["w"]) + 2 * PAD if w["emph"] else f.getlength(w["w"])


def merge_tokens(words):
    """Whisper splits '$2' ',400', '80' '%', 'full' '-time': glue them back together."""
    out = []
    for w in words:
        t = w["w"]
        if not t.strip(): continue
        if out and re.match(r"^[,.%]|^-[a-z]", t) and not re.match(r"^\.\.\.", t):
            out[-1]["w"] += t
            out[-1]["e"] = w["e"]
            out[-1]["ids"].append(w["i"])
        else:
            out.append({"w": t, "s": w["s"], "e": w["e"], "ids": [w["i"]]})
    return out


STOP = set("""about above after again also always another anything around because been before being between
both could didn't doesn't doing don't during each either every everything going gonna having here into itself just
like maybe more most much need never only other otherwise really right should something still than that that's their
them then there there's these they they're thing things this those through today together under until very want wanna
well were what what's when where whether which while with without would you'll you're your yourself""".split())


def auto_pick(page):
    """Most content-heavy word on the page: numbers first, then the longest non-filler word."""
    def clean(w): return re.sub(r"[^\w$%']", "", w["w"]).lower()
    cands = [w for w in page if (any(c.isdigit() for c in w["w"]) or len(clean(w)) >= 5) and clean(w) not in STOP]
    if not cands: return None
    best = max(cands, key=lambda w: (any(c.isdigit() for c in w["w"]), len(clean(w))))
    return best["ids"][0]


def paginate(words, emph, f, ef):
    pages, cur = [], []
    for i, w in enumerate(words):
        w["emph"] = any(j in emph for j in w["ids"])
        if cur:
            gap = w["s"] - cur[-1]["e"]
            prev = cur[-1]["w"]
            # an emphasis word may drop to its own line under the page, so allow it to overflow once
            lines = layout(cur + [w], f, ef)
            if (len(cur) >= 4 or gap > 0.45 or prev.endswith((".", "?", "!")) or len(lines) > 2
                    or (prev.endswith(",") and len(cur) >= 2)):
                pages.append(cur); cur = []
        cur.append(w)
    if cur: pages.append(cur)
    return pages


def layout(ws, f, ef):
    """Normal words share a line; an emphasis word that would overflow drops to the next line."""
    lines, line = [], []
    for w in ws:
        trial = line + [w]
        tw = sum(adv(x, f, ef) for x in trial) + f.getlength(" ") * (len(trial) - 1)
        if line and tw > MAX_W:
            lines.append(line); line = [w]
        else:
            line = trial
    if line: lines.append(line)
    return lines


def gradient(w, h, stops):
    """Left-to-right gradient through evenly spaced color stops."""
    x = np.linspace(0, 1, max(w, 2))
    pos = np.linspace(0, 1, len(stops))
    st = np.array(stops, float)
    g = np.stack([np.interp(x, pos, st[:, c]) for c in range(3)], -1)[None, :, :]
    return Image.fromarray(np.repeat(g, h, 0).astype(np.uint8))


def ease_pop(age, emph):
    """(alpha, scale, dy) for a word `age` seconds after it starts."""
    if age < 0: return 0, 1, 0
    a = min(1, age / 0.12)
    if emph:
        k = [(0, .78), (.1, 1.07), (.2, 1.0)]
        s = 1.0
        for (t0, v0), (t1, v1) in zip(k, k[1:]):
            if age < t1: s = v0 + (v1 - v0) * (age - t0) / (t1 - t0); break
        return a, s, 0
    return a, 1, (1 - a) * 10


def draw_page(page, t, st, f, ef, color_of):
    img = Image.new("RGBA", (W, STRIP_H), (0, 0, 0, 0))
    lines = layout(page, f, ef)
    asc_n, desc_n = f.getmetrics(); asc_e, desc_e = ef.getmetrics()
    heights = [(asc_e + desc_e) * .92 if any(w["emph"] for w in ln) else (asc_n + desc_n) * .95 for ln in lines]
    y = CENTER - sum(heights) / 2
    shadow = Image.new("L", (W, STRIP_H), 0)
    layers = []
    pill = None
    if page[0].get("bright"):
        widest = max(sum(adv(w, f, ef) for w in ln) + f.getlength(" ") * (len(ln) - 1) for ln in lines)
        top = CENTER - sum(heights) / 2
        pill = ((W - widest) / 2 - 30, top - 8, (W + widest) / 2 + 30, top + sum(heights) + 14)
    for ln, lh in zip(lines, heights):
        tw = sum(adv(w, f, ef) for w in ln) + f.getlength(" ") * (len(ln) - 1)
        x = (W - tw) / 2
        base = y + lh * 0.78
        for w in ln:
            fnt = ef if w["emph"] else f
            wa = adv(w, f, ef)
            a, s, dy = ease_pop(t - w["s"], w["emph"])
            if a > 0:
                layers.append((w, fnt, x, base + dy, wa, a, s))
            x += wa + f.getlength(" ")
        y += lh
    plate = st.get("plate")
    for w, fnt, x, base, wa, a, s in layers:
        # render each word on its own tile so it can scale around its center
        asc, desc = fnt.getmetrics()
        on_plate = plate and w["emph"]
        tile = Image.new("L", (int(wa) + 40, int(asc * 1.6) + 40), 0)
        ImageDraw.Draw(tile).text((20 + (PAD if on_plate else 0), 20), w["w"], font=fnt, fill=255)
        if on_plate:   # solid label from cap height to just under the baseline, like a logo plate
            cap_top = fnt.getbbox("H")[1]
            pv = int(fnt.size * 0.13)
            pm = Image.new("L", tile.size, 0)
            ImageDraw.Draw(pm).rounded_rectangle((20, 20 + cap_top - pv, 20 + wa, 20 + asc + desc * 0.45), plate.get("radius", 6), fill=255)
        cx, cy = x - 20 + tile.width / 2, base - asc - 20 + tile.height / 2   # unscaled tile center
        if s != 1:
            tile = tile.resize((max(1, int(tile.width * s)), max(1, int(tile.height * s))), Image.BICUBIC)
            if on_plate: pm = pm.resize(tile.size, Image.BICUBIC)
        px, py = int(cx - tile.width / 2), int(cy - tile.height / 2)
        m = tile.point(lambda v: int(v * a))
        if on_plate:
            pm = pm.point(lambda v: int(v * a))
            shadow.paste(255, (px, py + 3), pm)
            img.paste(Image.new("RGBA", tile.size, tuple(plate["fill"]) + (255,)), (px, py), pm)
            img.paste(Image.new("RGBA", tile.size, tuple(plate.get("text", (12, 12, 12))) + (255,)), (px, py), m)
            continue
        shadow.paste(255, (px, py + 3), m)
        if w["emph"] or w["act_s"] <= t < w["act_e"]:
            if st.get("gradient"):
                face = gradient(tile.width, tile.height, st["gradient"]).convert("RGBA")
            else:
                face = Image.new("RGBA", tile.size, color_of(w) + (255,))
        else:
            face = Image.new("RGBA", tile.size, tuple(st.get("text", (255, 255, 255))) + (255,))
        img.paste(face, (px, py), m)
    # two-layer shadow: wide soft glow for separation + tight contact shadow for edge definition
    wide = shadow.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(min(255, v * 1.6) * 0.55))
    tight = shadow.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.75))
    out = Image.new("RGBA", (W, STRIP_H), (0, 0, 0, 0))
    if pill:
        # fade the pill in with the page's first word so it never shows up empty
        r, g, b, pa = tuple(st.get("pill", (11, 11, 13, 210)))
        pa = int(pa * ease_pop(t - page[0]["s"], False)[0])
        if pa > 0:
            ImageDraw.Draw(out).rounded_rectangle(pill, 26, fill=(r, g, b, pa))
    for m in (wide, tight):
        layer = Image.new("RGBA", (W, STRIP_H), (0, 0, 0, 0)); layer.putalpha(m)
        out = Image.alpha_composite(out, layer)
    return Image.alpha_composite(out, img)


M709_2020 = np.array([[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0114], [0.0164, 0.0880, 0.8956]], np.float32)
_LUT = None


def to_hlg(img):
    """sRGB/BT.709 RGBA -> BT.2020 HLG rgba64le, graphics white at 75% signal (BT.2408)."""
    global _LUT
    a = np.asarray(img)
    if _LUT is None:
        v = np.arange(256, dtype=np.float32) / 255
        _LUT = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)
    with np.errstate(all="ignore"):
        e = np.clip(_LUT[a[..., :3]] @ M709_2020.T, 0, 1) * 0.2647
        hlg = np.where(e <= 1 / 12, np.sqrt(3 * e), 0.17883277 * np.log(np.maximum(12 * e - 0.28466892, 1e-9)) + 0.55991073)
    out = np.empty(a.shape, "<u2")
    out[..., :3] = np.clip(hlg, 0, 1) * 65535 + 0.5
    out[..., 3] = a[..., 3].astype(np.uint32) * 257
    return out.tobytes()


def main(P, k, style_name):
    global STRIP_Y, PAD
    c = common.clip(P, k)
    sty = common.style(P, style_name)
    st = sty["caption"]
    grade = (sty.get("grade") + ",") if sty.get("grade") else ""
    PAD = int((st.get("plate") or {}).get("pad", 16)) if st.get("plate") else 0
    center = int(c.get("caption_center") or DEFAULT_CENTER)
    STRIP_Y = min(max(center - CENTER, 0), H - STRIP_H)
    f = common.font(st["font"], st["size"])
    ef = common.font(st["emph_font"], st["emph_size"])
    src = common.base_video(P, k)
    wpath = os.path.join(P, "base", f"{k}.words.json")
    if not os.path.exists(wpath):
        common.die(f"{wpath} missing (build.py writes it; for source_file clips run transcribe.py --file)")
    fix = c.get("fix") or {}
    raw_words = [dict(w, w=fix.get(str(w["i"]), w["w"])) for w in json.load(open(wpath))]
    words = merge_tokens([w for w in raw_words if w["w"].strip()])      # "" fixes drop the word
    if st.get("upper"):
        for w in words: w["w"] = w["w"].upper()
    emph = set(c.get("emphasis") or [])
    for _ in range(3):   # every page gets at least one emphasis word; re-page since emphasis is wider
        pages = paginate(words, emph, f, ef)
        added = {auto_pick(p) for p in pages if not any(w["emph"] for w in p) and auto_pick(p) is not None}
        if not added: break
        emph |= added
    colors = [tuple(x) for x in st.get("colors") or []]
    for pi, p in enumerate(pages):
        for j, w in enumerate(p):
            nxt = p[j + 1]["s"] if j + 1 < len(p) else w["e"] + 0.35
            w["act_s"], w["act_e"], w["pc"] = w["s"], min(nxt, w["e"] + 0.3), pi % max(1, len(colors))
    color_of = (lambda w: colors[w["pc"]]) if colors else (lambda w: (255, 255, 255))
    spans = []
    for i, p in enumerate(pages):
        end = p[-1]["e"] + 0.5
        if i + 1 < len(pages): end = min(end, pages[i + 1][0]["s"])
        spans.append((p[0]["s"], end, p))
    dur = common.duration(src)
    hdr = common.is_hlg(src)
    sw, sh = common.dims(src)
    fit = "" if (sw, sh) == (W, H) else f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
    os.makedirs(os.path.join(P, "out"), exist_ok=True)
    dst = os.path.join(P, "out", f"{k}_{style_name}.mp4")
    band_y = STRIP_Y + CENTER - 110
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", src, "-vf",
                          f"{fit}crop=800:220:140:{band_y},scale=40:11,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    lum = np.frombuffer(raw, np.uint8).reshape(-1, 11 * 40).mean(axis=1) / 255
    for s0, e0, pg in spans:
        seg = lum[int(s0 * FPS):max(int(s0 * FPS) + 1, int(e0 * FPS))]
        pg[0]["bright"] = bool(len(seg) and np.median(seg) > (0.62 if hdr else 0.66))
    if hdr:   # iPhone HLG footage: convert captions into HLG and keep the file 10-bit HDR
        pix, conv = "rgba64le", to_hlg
        vf = (f"[1:v]scale=out_color_matrix=bt2020:out_range=tv,format=yuva444p10le[c];"
              f"[0:v]{fit}{grade}null[b];[b][c]overlay=0:{STRIP_Y}:format=yuv420p10:eof_action=pass,format=yuv420p10le[v]")
        venc = ["-c:v", "libx265", "-preset", "medium", "-crf", "15", "-tag:v", "hvc1",
                "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:range=limited",
                "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-color_range", "tv"]
    else:
        pix, conv = "rgba", (lambda im: im.tobytes())
        vf = f"[0:v]{fit}{grade}null[b];[b][1:v]overlay=0:{STRIP_Y}:eof_action=pass,format=yuv420p[v]"
        venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-profile:v", "high"]
    p = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
                          "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{W}x{STRIP_H}", "-r", str(FPS), "-i", "pipe:0",
                          "-filter_complex", vf, "-map", "[v]", "-map", "0:a", *venc,
                          "-c:a", "copy", "-movflags", "+faststart", dst], stdin=subprocess.PIPE)
    blank = conv(Image.new("RGBA", (W, STRIP_H), (0, 0, 0, 0)))
    cache_key, cache = None, blank
    for n in range(int(round(dur * FPS))):
        t = n / FPS
        sp = next((s for s in spans if s[0] <= t < s[1]), None)
        if sp is None:
            p.stdin.write(blank); continue
        ages = tuple(min(round((t - w["s"]) * FPS), 7) for w in sp[2]) + tuple(w["act_s"] <= t < w["act_e"] for w in sp[2])
        key = (id(sp), ages)
        if key != cache_key:
            cache = conv(draw_page(sp[2], t, st, f, ef, color_of)); cache_key = key
        p.stdin.write(cache)
    p.stdin.close(); p.wait()
    print("wrote", dst, len(pages), "pages", "HDR HLG" if hdr else "SDR", "rc", p.returncode, flush=True)
    if p.returncode: sys.exit(p.returncode)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    main(common.project(sys.argv[1]), sys.argv[2], sys.argv[3])
