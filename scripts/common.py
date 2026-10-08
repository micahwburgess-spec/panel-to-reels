"""Shared helpers for the panel-to-reels scripts (paths, project files, styles, fonts, ffprobe).

Every script takes a project dir P as its first argument. Layout:
  P/source.<ext>      the long video (fetch.py writes source.mkv)
  P/transcript.json   {"words": [{"i", "w", "s", "e"}, ...]}  (transcribe.py)
  P/transcript.txt    one line per whisper segment: [mm:ss] #<first word index> text
  P/clips.json        {"clips": {"A": {...}, ...}}  (see USAGE.md)
  P/styles.json       optional; falls back to the skill's styles.json
  P/base P/out P/covers P/frames P/sheets P/export   work dirs
"""
import json, os, subprocess, sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(SCRIPTS)
FONTS = os.path.join(SKILL, "fonts")
BIN = os.path.join(SKILL, "bin")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm")
W, H, FPS = 1080, 1920, 30


def die(msg):
    print("error:", msg, file=sys.stderr)
    sys.exit(1)


def project(arg):
    P = os.path.abspath(os.path.expanduser(arg))
    if not os.path.isdir(P):
        die(f"project dir not found: {P}")
    return P


def workdir(P, name):
    d = os.path.join(P, name)
    os.makedirs(d, exist_ok=True)
    return d


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def tool(name):
    """bin/<name> from setup.sh."""
    p = os.path.join(BIN, name)
    if not os.path.exists(p):
        die(f"{p} missing: run scripts/setup.sh")
    return p


# ---------- project files ----------

def source_video(P):
    for ext in VIDEO_EXTS:
        p = os.path.join(P, "source" + ext)
        if os.path.exists(p):
            return p
    die(f"no source video in {P} (expected source.mkv/.mp4/.mov/...; run fetch.py or copy one in)")


def load_words(P):
    p = os.path.join(P, "transcript.json")
    if not os.path.exists(p):
        die(f"{p} missing: run transcribe.py first")
    return json.load(open(p))["words"]


def load_clips(P):
    p = os.path.join(P, "clips.json")
    if not os.path.exists(p):
        die(f"{p} missing: write clips.json (see examples/clips.example.json)")
    d = json.load(open(p))
    return d.get("clips", d)


def clip(P, k):
    clips = load_clips(P)
    if k not in clips:
        die(f"clip {k!r} not in clips.json (have: {', '.join(clips)})")
    return clips[k]


def load_styles(P):
    p = os.path.join(P, "styles.json")
    if not os.path.exists(p):
        p = os.path.join(SKILL, "styles.json")
    d = json.load(open(p))
    return d.get("styles", d)


def style(P, name):
    styles = load_styles(P)
    if name not in styles:
        die(f"style {name!r} not found (have: {', '.join(styles)})")
    return styles[name]


def base_video(P, k, required=True):
    """P/base/<clip>.<ext>: the vertical 1080x1920 clip that captions and covers go onto."""
    for ext in VIDEO_EXTS:
        p = os.path.join(P, "base", k + ext)
        if os.path.exists(p):
            return p
    if required:
        die(f"no base video for clip {k} in {P}/base (run build.py, or transcribe.py --file for source_file clips)")
    return None


def mmss(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def parse_time(v):
    """'681.5', '11:21', '1:02:03' -> seconds."""
    parts = str(v).split(":")
    t = 0.0
    for p in parts:
        t = t * 60 + float(p)
    return t


# ---------- fonts ----------

def font(spec, size):
    """Font by filename in the skill's fonts/ dir. 'Sora:ExtraBold' picks a named instance of a variable font."""
    from PIL import ImageFont
    name, _, inst = spec.partition(":")
    if not os.path.splitext(name)[1]:
        name += ".ttf"
    path = name if os.path.isabs(name) else os.path.join(FONTS, name)
    if not os.path.exists(path):
        die(f"font {path} missing: run scripts/setup.sh or drop the .ttf into {FONTS}")
    f = ImageFont.truetype(path, size)
    if inst:
        f.set_variation_by_name(inst)
    return f


# ---------- ffprobe ----------

def probe(src, entries, stream="v:0"):
    args = ["ffprobe", "-v", "error"]
    if stream:
        args += ["-select_streams", stream]
    out = subprocess.check_output(args + ["-show_entries", entries, "-of", "csv=p=0", src]).decode().strip()
    return out.splitlines()[0].rstrip(",") if out else ""


def duration(src):
    return float(probe(src, "format=duration", stream=None))


def dims(src):
    w, h = probe(src, "stream=width,height").split(",")[:2]
    return int(w), int(h)


def is_hlg(src):
    # ffprobe csv can end with a trailing comma ("arib-std-b67,"): probe() strips it
    return probe(src, "stream=color_transfer") == "arib-std-b67"


def has_audio(src):
    return bool(probe(src, "stream=codec_type", stream="a"))
