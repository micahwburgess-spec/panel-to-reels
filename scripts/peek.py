"""Contact sheet of N frames between two source times, for checking who is on camera.

Usage: peek.py P START END [N=12]
  START/END  absolute source seconds (or mm:ss)
  -> P/sheets/peek_<START>.jpg  (4 columns, each frame labeled with its time)
"""
import os, sys
import common, hlg
from PIL import Image, ImageDraw

COLS, TW = 4, 480


def label_font():
    try: return common.font("Poppins-SemiBold.ttf", 22)
    except SystemExit:
        from PIL import ImageFont
        return ImageFont.load_default()


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    P = common.project(sys.argv[1])
    s, e = common.parse_time(sys.argv[2]), common.parse_time(sys.argv[3])
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    src = common.source_video(P)
    sw, sh = common.dims(src)
    th = int(round(TW * sh / sw / 2)) * 2
    times = [s + (e - s) * (i + 0.5) / n for i in range(n)]
    rows = (n + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TW, rows * th), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    fnt = label_font()
    for i, t in enumerate(times):
        x, y = (i % COLS) * TW, (i // COLS) * th
        sheet.paste(hlg.frame(src, t, TW, th), (x, y))
        tag = f"{t:.1f}s  {common.mmss(t)}"
        d.rectangle([x, y, x + int(fnt.getlength(tag)) + 16, y + 34], fill=(0, 0, 0))
        d.text((x + 8, y + 4), tag, font=fnt, fill=(255, 220, 0))
    out = os.path.join(common.workdir(P, "sheets"), f"peek_{sys.argv[2].replace(':', '-')}.jpg")
    sheet.save(out, quality=88)
    print("wrote", out)


if __name__ == "__main__":
    main()
