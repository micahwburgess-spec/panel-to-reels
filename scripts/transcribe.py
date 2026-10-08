"""Word-level transcript with mlx-whisper (large-v3-turbo, runs on the Apple GPU).

Usage:
  transcribe.py P [--prompt "names, jargon"] [--language en]
      -> P/transcript.json  {"words": [{"i", "w", "s", "e"}], "segments": [...]}
         P/transcript.txt   one line per segment: [mm:ss] #<first word index> text
  transcribe.py P --file VIDEO --clip ID [--prompt ...]
      solo mode, for an already-edited vertical video (set "source_file" on that clip):
      -> P/base/<ID>.words.json (clip-time words, i = 0..n), P/base/<ID>.words.txt,
         and P/base/<ID>.<ext> linked to VIDEO. Nothing else is touched.
Words are deduped by (round(start, 2), word): whisper sometimes repeats a word across segments.
"""
import argparse, json, os, subprocess, sys, tempfile
import common

MODEL = "mlx-community/whisper-large-v3-turbo"


def whisper(video, prompt=None, language=None):
    import mlx_whisper
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "audio16k.wav")
        common.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])
        print("transcribing", os.path.basename(video), "with", MODEL, "...", flush=True)
        kw = {"path_or_hf_repo": MODEL, "word_timestamps": True}
        if prompt: kw["initial_prompt"] = prompt
        if language: kw["language"] = language
        res = mlx_whisper.transcribe(wav, **kw)
    segs = []
    for sg in res["segments"]:
        ws = [{"w": w["word"].strip(), "s": round(float(w["start"]), 2), "e": round(float(w["end"]), 2)}
              for w in sg.get("words", []) if w["word"].strip()]
        segs.append({"s": round(float(sg["start"]), 2), "e": round(float(sg["end"]), 2), "t": sg["text"].strip(), "words": ws})
    return segs


def flatten(segs):
    """One deduped, time-sorted word list with global indices, plus each segment's first word index."""
    uniq = {}
    for sg in segs:
        for w in sg["words"]:
            uniq.setdefault((round(w["s"], 2), w["w"]), w)
    words = sorted(uniq.values(), key=lambda w: w["s"])
    index = {(round(w["s"], 2), w["w"]): i for i, w in enumerate(words)}
    out = [{"i": i, "w": w["w"], "s": w["s"], "e": w["e"]} for i, w in enumerate(words)]
    lines, segments = [], []
    for sg in segs:
        if not sg["words"]: continue
        i0 = index[(round(sg["words"][0]["s"], 2), sg["words"][0]["w"])]
        segments.append({"s": sg["s"], "e": sg["e"], "i": i0, "t": sg["t"]})
        lines.append(f"[{common.mmss(sg['s'])}] #{i0} {sg['t']}")
    return out, segments, lines


def main():
    ap = argparse.ArgumentParser(description="Transcribe with word timestamps")
    ap.add_argument("P")
    ap.add_argument("--prompt", help="names and jargon to bias spelling, e.g. 'Summit Oak AI, Claude, EBI'")
    ap.add_argument("--language", help="e.g. en (default: auto-detect)")
    ap.add_argument("--file", help="solo mode: an already-edited vertical video")
    ap.add_argument("--clip", help="solo mode: clip ID in clips.json")
    a = ap.parse_args()
    P = common.project(a.P)
    if bool(a.file) != bool(a.clip):
        common.die("--file and --clip go together")

    if a.file:
        video = os.path.abspath(os.path.expanduser(a.file))
        if not os.path.exists(video): common.die(f"{video} not found")
        base = common.workdir(P, "base")
        words, _, lines = flatten(whisper(video, a.prompt, a.language))
        json.dump(words, open(os.path.join(base, f"{a.clip}.words.json"), "w"), indent=0)
        open(os.path.join(base, f"{a.clip}.words.txt"), "w").write("\n".join(lines) + "\n")
        for x in common.VIDEO_EXTS:   # clear dangling links left by a moved file
            p = os.path.join(base, a.clip + x)
            if os.path.islink(p) and not os.path.exists(p): os.remove(p)
        old = common.base_video(P, a.clip, required=False)
        if old and os.path.islink(old):
            os.remove(old); old = None
        link = os.path.join(base, a.clip + os.path.splitext(video)[1].lower())
        if old:
            link = old
            print(f"note: {old} is a real file, left in place (delete it to link {video} instead)")
        else:
            os.symlink(video, link)
        print(f"wrote base/{a.clip}.words.json ({len(words)} words), base/{a.clip}.words.txt, linked {link}")
        return

    src = common.source_video(P)
    words, segments, lines = flatten(whisper(src, a.prompt, a.language))
    json.dump({"source": os.path.basename(src), "words": words, "segments": segments},
              open(os.path.join(P, "transcript.json"), "w"))
    open(os.path.join(P, "transcript.txt"), "w").write("\n".join(lines) + "\n")
    print(f"wrote transcript.json ({len(words)} words) and transcript.txt ({len(lines)} lines)")


if __name__ == "__main__":
    main()
