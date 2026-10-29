"""Reel covers (1080x1920 JPG) with a stacked Anton headline over a still from the clip.

Usage: cover.py P CLIP STYLE          -> P/covers/<CLIP>_<STYLE>.jpg

Text sits inside the 3:4 band Instagram shows on the profile grid (y 240-1680).
Clip keys (clips.json):
  headline     caps headline; words inside *...* get the accent, e.g. "YOUR WEBSITE HAS *TWO JOBS.*"
  accent       accent name from the style's cover.accents (e.g. gold, red, blue), or [r,g,b]
  cover_time   seconds into the finished clip for the still (default 1/3 of the clip)
  cover_shift  px to slide the photo up so the face clears the headline (its new bottom edge fades into the tint)
  lockup       optional [top, bottom] override of the style's lockup
The "cover" block of a style:
  headline_font, lockup_font   font files in fonts/
  accents / tints              {name: [r,g,b]}: solid accent per clip, bottom tint to match
  gradient                     [[r,g,b], ...]: accent words + rule filled with this gradient instead
  tint                         bottom tint when the accent has none in tints
  bloom                        {"color": [r,g,b], "strength": 0.45}: soft glow behind the headline
  lockup                       [top, bottom] letterspaced lines under the rule, joined by separator
  separator, separator_color   e.g. "×" and "accent" or [r,g,b]
  plate                        {"fill": [r,g,b], "text": [r,g,b]}: accent lines sit on a solid bar instead of
                               being colored (a logo-style label)
The style's top-level "grade" (an ffmpeg filter chain, see captions.py) is applied to the still too.
"""
import os, re, subprocess, sys
from itertools import combinations
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import common, hlg

W, H = common.W, common.H
SAFE_TOP, SAFE_BOTTOM = 240, 1680


def gradient(w, h, stops):
    x = np.linspace(0, 1, max(w, 2))
    pos = np.linspace(0, 1, len(stops))
    st = np.array(stops, float)
    g = np.stack([np.interp(x, pos, st[:, c]) for c in range(3)], -1)[None, :, :]
    return Image.fromarray(np.repeat(g, h, 0).astype(np.uint8)).convert("RGBA")


def tokens(markup):
    out, hot = [], False
    for part in re.split(r"(\*)", markup):
        if part == "*": hot = not hot; continue
        out += [(w, hot) for w in part.split()]
    return out


def wrap(toks, font, maxw):
    """Balanced wrap: white run and accent run each start fresh lines, split as evenly as possible."""
    groups, cur = [], []
    for t in toks:
        if cur and t[1] != cur[-1][1]: groups.append(cur); cur = []
        cur.append(t)
    groups.append(cur)
    width = lambda ln: font.getlength(" ".join(w for w, _ in ln))
    lines = []
    for g in groups:
        for n in range(1, len(g) + 1):
            best = None
            for cuts in combinations(range(1, len(g)), n - 1):
                parts = [g[a:b] for a, b in zip((0,) + cuts, cuts + (len(g),))]
                worst = max(width(p) for p in parts)
                if worst <= maxw and (best is None or worst < best[0]): best = (worst, parts)
            if best: lines += best[1]; break
        else:
            lines += [[t] for t in g]
    return lines


def graded(img, grade):
    """Run a still through the same ffmpeg filter chain the video gets."""
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-i", "-", "-vf", f"format=yuv420p,{grade},format=rgb24", "-f", "rawvideo", "-"],
                         input=img.convert("RGB").tobytes(), capture_output=True, check=True).stdout
    return Image.frombytes("RGB", (W, H), out)


def headline_masks(lines, font, size, bottom, plate=False):
    lh = int(size * (1.08 if plate else 0.94))
    top = bottom - lh * len(lines)
    shadow, hot_mask, white_mask, plate_mask = (Image.new("L", (W, H), 0) for _ in range(4))
    sd, hd, wd = ImageDraw.Draw(shadow), ImageDraw.Draw(hot_mask), ImageDraw.Draw(white_mask)
    for i, ln in enumerate(lines):
        y = top + i * lh
        lw = font.getlength(" ".join(w for w, _ in ln))
        x = (W - lw) / 2
        if plate and ln[0][1]:   # one solid bar per accent line, cap height plus padding
            cap_top, cap_bot = font.getbbox("H")[1], font.getbbox("H")[3]
            pad = int(size * 0.16)
            ImageDraw.Draw(plate_mask).rectangle((x - pad * 1.4, y + cap_top - pad, x + lw + pad * 1.4, y + cap_bot + pad), fill=255)
        for w, hot in ln:
            (hd if hot else wd).text((x, y), w, font=font, fill=255)
            if not (plate and hot): sd.text((x, y + 6), w, font=font, fill=255)
            x += font.getlength(w + " ")
    if plate: ImageDraw.Draw(shadow).bitmap((0, 6), plate_mask, fill=255)
    return shadow, hot_mask, white_mask, plate_mask


def main(P, k, style_name):
    c = common.clip(P, k)
    sty = common.style(P, style_name)
    cv = sty["cover"]
    plate = cv.get("plate")
    src = common.base_video(P, k)
    t = c.get("cover_time")
    if t is None: t = common.duration(src) / 3
    shift = int(c.get("cover_shift") or 0)
    headline = c.get("headline") or c.get("title", k).upper()
    acc = c.get("accent")
    accents = {n: tuple(v) for n, v in (cv.get("accents") or {}).items()}
    if isinstance(acc, list): acc_rgb = tuple(acc)
    else: acc_rgb = accents.get(acc) or next(iter(accents.values()), (236, 178, 52))
    tints = cv.get("tints") or {}
    tint = tuple(tints[acc]) if isinstance(acc, str) and acc in tints else tuple(cv.get("tint", (11, 11, 13)))
    grad = cv.get("gradient")

    img = hlg.frame(src, t)   # tone-maps iPhone HLG footage to SDR for the still
    if sty.get("grade"): img = graded(img, sty["grade"])
    if shift:   # slide the photo up so the face clears the headline, fading its new bottom edge into the tint
        img = img.crop((0, shift, W, H))
        fade = Image.linear_gradient("L").rotate(180).resize((W, 220))
        mask = Image.new("L", img.size, 255); mask.paste(fade, (0, img.height - 220))
        canvas = Image.new("RGB", (W, H), tint); canvas.paste(img, (0, 0), mask); img = canvas
    # bottom gradient: clear above ~45%, deep tint by the lockup
    yv = np.linspace(0, 1, H)[:, None, None]
    a = np.clip((yv - 0.42) / 0.40, 0, 1) ** 1.3 * 0.94
    base = np.asarray(img, np.float32)
    base = base * (1 - a) + np.array(tint, np.float32) * a
    if cv.get("bloom"):   # faint glow behind the headline
        yy, xx = np.mgrid[0:H, 0:W]
        bloom = np.exp(-(((xx - W / 2) / 520) ** 2 + ((yy - 1250) / 260) ** 2))[..., None]
        base += bloom * np.array(cv["bloom"]["color"], np.float32) * cv["bloom"].get("strength", 0.45)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")

    # headline: Anton caps, sized so the block fits ~900px wide and <= 4 lines
    toks = tokens(headline)
    for size in range(172, 96, -4):
        font = common.font(cv.get("headline_font", "Anton-Regular.ttf"), size)
        lines = wrap(toks, font, 860 if plate else 920)
        widow = any(len(ln) == 1 and font.getlength(ln[0][0]) < 0.42 * 920 and i > 0 and lines[i - 1][-1][1] == ln[0][1]
                    for i, ln in enumerate(lines))
        if len(lines) <= 4 and not widow: break
    lockup = c.get("lockup") or cv.get("lockup") or []
    lockup_h = {0: 0, 1: 34 + 36}.get(len(lockup), 112 + 32)   # rule-to-lockup-bottom height
    bottom = 1430
    for _ in range(2):   # keep everything inside the grid-safe band: lift the block if the lockup would spill
        shadow, hot_mask, white_mask, plate_mask = headline_masks(lines, font, size, bottom, bool(plate))
        text_bottom = max((m.getbbox() or (0, 0, 0, bottom))[3] for m in (hot_mask, white_mask, plate_mask))
        spill = text_bottom + 40 + lockup_h - SAFE_BOTTOM
        if spill <= 0: break
        bottom -= spill
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.putalpha(shadow.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.6)))
    img = Image.alpha_composite(img, sh)
    img.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), white_mask)
    if plate:
        img.paste(Image.new("RGBA", (W, H), tuple(plate["fill"]) + (255,)), (0, 0), plate_mask)
        hot_fill = Image.new("RGBA", (W, H), tuple(plate.get("text", (12, 12, 12))) + (255,))
    elif grad:   # gradient spans the hot words' own extent, not the whole canvas
        hot_fill = Image.new("RGBA", (W, H))
        bb = hot_mask.getbbox()
        if bb: hot_fill.paste(gradient(bb[2] - bb[0], bb[3] - bb[1], grad), (bb[0], bb[1]))
    else:
        hot_fill = Image.new("RGBA", (W, H), acc_rgb + (255,))
    img.paste(hot_fill, (0, 0), hot_mask)

    # accent rule + lockup
    d = ImageDraw.Draw(img)
    ry = text_bottom + 40
    if grad:
        img.paste(gradient(150, 4, grad), (W // 2 - 75, ry))
    else:
        d.rectangle([W // 2 - 75, ry, W // 2 + 75, ry + 3], fill=acc_rgb)
    lf = cv.get("lockup_font", "Poppins-SemiBold.ttf")
    f1, f2 = common.font(lf, 30), common.font(lf, 25)

    def spaced(text, y, font, track, fill):
        widths = [font.getlength(ch) for ch in text]
        total = sum(widths) + track * (len(text) - 1)
        x = (W - total) / 2
        for ch, cw in zip(text, widths):
            d.text((x, y), ch, font=font, fill=fill); x += cw + track

    sep_col = cv.get("separator_color", "accent")
    if sep_col == "accent":
        sep_col = acc_rgb if not grad else tuple(grad[len(grad) // 2])
    if lockup:
        spaced(lockup[0], ry + 34, f1, 11, (255, 255, 255))
    if len(lockup) > 1:
        spaced(cv.get("separator", "×"), ry + 78, f2, 0, tuple(sep_col))
        spaced(lockup[1], ry + 112, f2, 8, (236, 236, 240))
    out = os.path.join(common.workdir(P, "covers"), f"{k}_{style_name}.jpg")
    img.convert("RGB").save(out, quality=94)
    print("cover", out, flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    main(common.project(sys.argv[1]), sys.argv[2], sys.argv[3])
