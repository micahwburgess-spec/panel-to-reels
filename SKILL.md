---
name: panel-to-reels
description: Turn a long talk, panel, podcast or interview recording into vertical 9:16 reels with word-by-word build-up captions and Instagram-grid covers, in two caption styles. Also re-captions already-edited vertical videos, including iPhone HDR footage. Use when someone wants shorts, reels or clips cut from a long video, burned-in captions, or reel covers. Triggers include "cut clips from this", "make reels from this panel", "turn this into shorts", "caption this video", "make covers for these reels".
---

# Panel to Reels

Turns one long recording into a batch of ready-to-post vertical reels. Each reel is cut on word boundaries, reframed to 9:16 around the speaker's face, captioned word by word, and paired with a cover built for the Instagram profile grid. Every clip renders in two styles: **buildup** (white captions, red / blue / magenta emphasis) and **brand** (your colors and fonts, set in `styles.json`).

The scripts do the mechanical work. The quality comes from the judgment calls in this file. Follow the workflow in order and do not skip the review gates.

## Requirements

- Mac with Apple Silicon (face tracking uses Apple Vision, transcription uses mlx-whisper on the GPU).
- `ffmpeg` with `libx264` and `libx265` (`brew install ffmpeg`).
- Python 3 (the setup script builds its own venv in `~/.panel-to-reels/`).
- Disk: a 90-minute 4K source is about 6 GB.

One-time setup, from this skill's folder:

```bash
bash scripts/setup.sh
```

Run every script through the wrapper so it uses the right Python: `bash scripts/run.sh <script> <args>`. The exact command line for each script is in `scripts/USAGE.md`.

## The workflow

Work in a project folder P (anywhere durable, never `/tmp`, which macOS purges). Every script takes P as its first argument.

### 1. Get the source at the highest resolution available
`run.sh fetch P <url>` or copy a local file to `P/source.<ext>`. A 9:16 crop of a 16:9 frame keeps about a third of the width, so 4K in means sharp reels out. 1080p sources work but punch-ins look soft. If the person owns the recording, ask for the original camera files; they beat any upload.

### 2. Transcribe
`run.sh transcribe P --prompt "speaker names, company names, jargon"`. The prompt matters: names come out right far more often. This writes `transcript.txt` with a word index at the start of every line. You pick clips by those indices.

### 3. If the person has a reference style, study it first
Ask for 2 to 6 example posts. Instagram blocks direct downloads, but public embed pages (`instagram.com/reel/<id>/embed/captioned/`) often expose one video and always show the caption copy. Pull frames and note: caption font, size, position, how words appear, which words get color, cover headline font and layout. Map what you see onto `styles.json` before rendering anything.

### 4. Read the whole transcript and pick moments
Read all of it. Do not skim the first half. A good clip:
- Is one self-contained idea in 20 to 80 seconds.
- Opens on a strong line: a claim, a number, a question or a story beat. If the best line is mid-answer, start there.
- Ends on a payoff, not mid-thought.

Weigh toward the person you are making these for (their own answers first). Skip moments the event or another account has already posted; ask the person or check their links. Present the shortlist as a table (clip, speaker, the hook line, timestamp) and let the person cut or add before you build.

### 5. Confirm the speaker is on camera (do not skip)
`run.sh peek P <start> <end>` for every candidate. Multi-camera edits often cut to a reaction shot or a wide while someone talks. Rules:
- If the speaker is off camera for most of the clip, drop it. A vertical crop would put someone else's face over their words.
- A short reaction cutaway (under about a third of the clip) can stay in `letterbox` mode: the wide shot sits over a blurred fill, so nobody is misidentified.
- Identify people by what they wear and where they sit, then confirm against the transcript (who is introduced, who answers). Do not guess names from appearance.

### 6. Cut on word indices
Write each clip into `P/clips.json` (schema in `scripts/USAGE.md`, example in `examples/clips.example.json`).
- `spans` are inclusive word-index ranges. Several spans make jump cuts. Use them to tighten rambling, never to change what someone meant.
- `fix` corrects transcription errors you are sure of ("pounded" said as "found", "Claude on a D file" meaning "CLAUDE.md"). An empty string deletes a word.
- If a phrase is garbled and you cannot be sure what was said, cut around it. Do not guess words into someone's mouth.
- When a clip opens on a host's question, keep the question only as setup. Never let the host's lines read as the guest's.

### 7. Frame
`run.sh shots P <clips>` finds camera cuts (including slow dissolves), renders one ruled frame per shot, and prints the face centers it detects. Put the speaker's x into `framing` for each shot.
- `crop` is the crop height as a fraction of the source: about 0.62 for a medium shot of three or four people, 0.42 to 0.5 for a wide shot.
- Handheld cameras that pan need a framing mark for each move; the tracker follows smooth motion but can lose a fast whip.
- Neighbors sitting close together: give the exact x from the printed face centers, not an eyeballed one.

### 8. Build and check
`run.sh build P <clips>`, then pull 10 to 16 frames across each base clip. The speaker must be framed in every frame. Fix framing and rebuild before captions.

### 9. Captions, emphasis and covers
- Emphasis: hand-pick the words that carry the idea (numbers, names, the noun the point lands on) in `emphasis`. Any caption page without one gets an automatic pick.
- Headline: 4 to 9 words, faithful to what was said, punchy. Wrap the payoff in `*asterisks*` so it gets the accent. It must not claim more than the speaker did.
- Cover frame: speaker facing the lens, mouth closed if possible. If the headline covers the mouth, raise `cover_shift` (it slides the photo up and fades the edge).
- Talking-head selfie footage sits lower in frame than panel footage: set `caption_center` near 1430 so captions sit on the chest, not the mouth.

### 10. Render, review, ship
`run.sh render_all P` renders every clip in every style, exports to `P/export/<Style>/`, and prints a verification table. Then review it yourself: a contact sheet of all covers at grid size, and three or four frames from each reel. Finally, write post copy for each clip in the person's voice. Quotes must match the transcript word for word. Tag only handles you have confirmed. Mark unknown handles `[handle]` for the person to fill in.

## Hard rules
- Never attribute words to the wrong person. When in doubt, drop the clip.
- Quotes in captions, covers and post copy match the transcript exactly.
- Never put another organization's name or branding on content that is not theirs. Lockups come from `styles.json`; set them per project.
- No invented numbers, results or claims in headlines or copy.
- Faces and voices are only the real recording. Never generate or clone a speaker.

## Already-edited vertical videos
For finished talking-head videos (including iPhone HDR), skip cutting and framing: `run.sh transcribe P --file <video> --clip <ID>`, add the clip to `clips.json` with `"source_file"` set and `"caption_center": 1430`, then `run.sh render_all P --clips <ID>`. Indices for `fix` and `emphasis` come from `P/base/<ID>.words.txt`. The source file is never modified.

## Styles and lockups
`styles.json` holds the presets. Each has a `label` (the export folder name), a `caption` block (fonts, sizes, highlight colors that cycle per caption page or a gradient, pill color) and a `cover` block (accent colors, bottom tints, lockup lines, separator, optional bloom). Copy it into P and edit it to customize a project. `examples/summit-oak-styles.json` shows a fully branded setup. Fonts load by filename from this skill's `fonts/` folder; variable fonts use `"Sora:ExtraBold"` syntax.

The lockup is the two small lines under every cover headline. Set it in the style, and override it per clip with `"lockup": ["LINE ONE", "LINE TWO"]` in `clips.json`. Event clips carry the event; a person's own videos carry their own name and brand, never the event's.

## Gotchas learned the hard way
- **iPhone footage is HDR (HLG).** Overlaying normal sRGB graphics makes them glow and oversaturate. The scripts detect HLG and convert captions into HDR and keep 10-bit HEVC output. Previews from Finder or plain ffmpeg grabs look dim and flat; judge with `hlg.frame()` stills or on a phone.
- **ffprobe csv output can carry a trailing comma** (`arib-std-b67,`). Compare with `in` or strip it.
- **Edited panels often use dissolves, not hard cuts.** Scene-score detection misses them; the frame-difference detector in `shots.py` catches them.
- **White captions vanish on white app screens.** Captions automatically get a dark pill when the background behind them is bright.
- **Whisper splits tokens** like `$2` `,400` and `80` `%`. Captions glue them back together, so emphasis indices point at the first piece.
- **Instagram shows covers cropped to 3:4** on the profile grid (y 240 to 1680 of 1920). Keep all cover text inside that band.
- **macOS purges `/tmp` after a few days.** Keep projects and the venv somewhere durable.
- Some ffmpeg builds lack `drawtext` and some Intel builds cannot use the hardware encoder. The scripts use PIL for all text and `libx265` for HDR, so they work either way.

---
Built by Micah Burgess, Summit Oak AI. summitoakai.com
