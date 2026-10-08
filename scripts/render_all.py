"""Render every clip x style end to end, export with readable names, and verify the files.

Usage: render_all.py P [--clips A,B] [--styles buildup,brand] [--rebuild]
  1. base video per clip: build.py when P/base/<clip> is missing (or --rebuild);
     source_file clips are linked + transcribed with transcribe.py --file when needed
  2. captions.py for every clip x style, 2 workers in parallel
  3. cover.py for every clip x style
  4. export to P/export/<Style label>/<NN - Title (Speaker)>.mp4 and "... - Cover.jpg"
     (NN = the clip's position in clips.json)
  5. ffprobe every exported mp4 (1080x1920, has audio, duration > 0) and print a report table
Default styles: every style in styles.json.
"""
import argparse, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import common

HERE = common.SCRIPTS


def step(script, *args):
    """Run a sibling script with this venv python; returns (ok, output)."""
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    r = subprocess.run([sys.executable, "-s", os.path.join(HERE, script), *args], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.returncode == 0, r.stdout.strip()


def safe(name):
    return re.sub(r'[/:\\]+', "-", name).strip()


def main():
    ap = argparse.ArgumentParser(description="Build, caption, cover, export and verify every clip")
    ap.add_argument("P")
    ap.add_argument("--clips", help="comma list (default: all in clips.json)")
    ap.add_argument("--styles", help="comma list (default: all in styles.json)")
    ap.add_argument("--rebuild", action="store_true", help="re-run build.py even when the base video exists")
    a = ap.parse_args()
    P = common.project(a.P)
    clips = common.load_clips(P)
    styles = common.load_styles(P)
    order = {k: n + 1 for n, k in enumerate(clips)}
    ks = a.clips.split(",") if a.clips else list(clips)
    ss = a.styles.split(",") if a.styles else list(styles)
    for k in ks:
        if k not in clips: common.die(f"clip {k!r} not in clips.json")
    for s in ss:
        if s not in styles: common.die(f"style {s!r} not in styles.json")
    failed = []

    # 1. base videos
    for k in ks:
        c = clips[k]
        if c.get("source_file"):
            sf = os.path.abspath(os.path.expanduser(c["source_file"]))
            words = os.path.join(P, "base", f"{k}.words.json")
            if not common.base_video(P, k, required=False) or not os.path.exists(words):
                print(f"[{k}] transcribing source_file {sf}", flush=True)
                ok, out = step("transcribe.py", P, "--file", sf, "--clip", k)
                print(out.splitlines()[-1] if out else "", flush=True)
                if not ok: failed.append((k, "-", "transcribe", out)); continue
        elif a.rebuild or not common.base_video(P, k, required=False):
            print(f"[{k}] building base video", flush=True)
            ok, out = step("build.py", P, k)
            print(out.splitlines()[-1] if out else "", flush=True)
            if not ok: failed.append((k, "-", "build", out))
    ready = [k for k in ks if common.base_video(P, k, required=False) and not any(f[0] == k for f in failed)]

    # 2. captions, two at a time
    jobs = [(k, s) for k in ready for s in ss]

    def cap(job):
        k, s = job
        return job, step("captions.py", P, k, s)
    with ThreadPoolExecutor(2) as ex:
        for (k, s), (ok, out) in ex.map(cap, jobs):
            print(f"[{k} {s}] {out.splitlines()[-1] if out else ''}", flush=True)
            if not ok: failed.append((k, s, "captions", out))

    # 3. covers
    for k, s in jobs:
        ok, out = step("cover.py", P, k, s)
        print(f"[{k} {s}] {out.splitlines()[-1] if out else ''}", flush=True)
        if not ok: failed.append((k, s, "cover", out))

    # 4. export
    exported = []
    for k, s in jobs:
        c = clips[k]
        label = styles[s].get("label") or s.title()
        name = f"{order[k]:02d} - {safe(c.get('title') or k)}"
        if c.get("speaker"): name += f" ({safe(c['speaker'])})"
        d = common.workdir(P, os.path.join("export", safe(label)))
        vid = os.path.join(P, "out", f"{k}_{s}.mp4")
        cov = os.path.join(P, "covers", f"{k}_{s}.jpg")
        if os.path.exists(vid) and not any(f[:2] == (k, s) and f[2] == "captions" for f in failed):
            shutil.copy2(vid, os.path.join(d, name + ".mp4"))
            exported.append((k, s, os.path.join(d, name + ".mp4")))
        if os.path.exists(cov) and not any(f[:2] == (k, s) and f[2] == "cover" for f in failed):
            shutil.copy2(cov, os.path.join(d, name + " - Cover.jpg"))

    # 5. verify
    print("\nREPORT")
    print(f"{'clip':<6}{'style':<10}{'size':<11}{'codec':<7}{'pix_fmt':<14}{'transfer':<14}{'audio':<7}{'dur':>7}  status  file")
    for k, s, path in exported:
        w, h = common.dims(path)
        codec = common.probe(path, "stream=codec_name")
        pix = common.probe(path, "stream=pix_fmt")
        trc = common.probe(path, "stream=color_transfer") or "-"
        aud = common.has_audio(path)
        dur = common.duration(path)
        base_dur = common.duration(common.base_video(P, k))
        good = (w, h) == (1080, 1920) and aud and dur > 0 and abs(dur - base_dur) < 0.5
        print(f"{k:<6}{s:<10}{f'{w}x{h}':<11}{codec:<7}{pix:<14}{trc:<14}{'yes' if aud else 'NO':<7}{dur:7.2f}  "
              f"{'OK' if good else 'CHECK'}    {os.path.relpath(path, P)}")
        if not good: failed.append((k, s, "verify", f"{w}x{h} audio={aud} dur={dur:.2f} base={base_dur:.2f}"))
    if failed:
        print("\nFAILURES")
        for k, s, what, out in failed:
            print(f"--- {k} {s} {what}\n{out[-2000:]}")
        sys.exit(1)
    print(f"\nall {len(exported)} videos OK -> {os.path.join(P, 'export')}")


if __name__ == "__main__":
    main()
