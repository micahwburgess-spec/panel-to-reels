"""Download a long video (YouTube or anything yt-dlp handles) into a project as P/source.mkv.

Usage: fetch.py P URL [--section START-END] [--force]
  P          project dir (created if missing)
  URL        video page URL
  --section  only download START-END (seconds or mm:ss / h:mm:ss), e.g. 676-765 or 11:16-12:45.
             Times in the transcript are then relative to the start of the section.
  --force    replace an existing P/source.*
Best video up to 2160p + best audio, merged. Writes P/source.json with the URL, title and section.
"""
import argparse, json, os, shutil, subprocess, sys
import common


def main():
    ap = argparse.ArgumentParser(description="Download a video into P/source.mkv")
    ap.add_argument("P")
    ap.add_argument("url")
    ap.add_argument("--section")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    P = os.path.abspath(os.path.expanduser(a.P))
    os.makedirs(P, exist_ok=True)
    old = [os.path.join(P, "source" + x) for x in common.VIDEO_EXTS if os.path.exists(os.path.join(P, "source" + x))]
    if old and not a.force:
        common.die(f"{old[0]} already exists (use --force to replace it)")
    for f in old:
        os.remove(f)

    ytdlp = common.tool("yt-dlp")
    extra = []
    if not shutil.which("deno") and shutil.which("node"):   # YouTube needs a JS runtime; yt-dlp defaults to deno
        extra += ["--js-runtimes", "node:" + shutil.which("node")]
    ff = shutil.which("ffmpeg")
    if ff:
        extra += ["--ffmpeg-location", os.path.dirname(ff)]

    info = json.loads(subprocess.check_output([ytdlp, "-J", "--no-playlist", *extra, a.url]))
    print("title:   ", info.get("title"), flush=True)
    print("duration:", info.get("duration"), "s", f"({common.mmss(info.get('duration') or 0)})", flush=True)

    cmd = [ytdlp, "--no-playlist", *extra, "-f", "bv*[height<=2160]+ba/b[height<=2160]/bv*+ba/b",
           "--merge-output-format", "mkv", "-o", os.path.join(P, "source.%(ext)s"), a.url]
    if a.section:
        s, _, e = a.section.partition("-")
        # ffmpeg does the section cut; keep its console output down to errors
        cmd[1:1] = ["--download-sections", f"*{common.parse_time(s)}-{common.parse_time(e)}",
                    "--downloader-args", "ffmpeg:-hide_banner -v error"]
    common.run(cmd)

    src = common.source_video(P)
    w, h = common.dims(src)
    dur = common.duration(src)
    json.dump({"url": a.url, "title": info.get("title"), "section": a.section, "file": os.path.basename(src)},
              open(os.path.join(P, "source.json"), "w"), indent=1)
    print(f"wrote {src}  {w}x{h}  {dur:.1f}s")


if __name__ == "__main__":
    main()
