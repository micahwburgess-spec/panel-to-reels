# panel-to-reels scripts: usage

Turns a long talking or panel video into vertical 1080x1920 reels with build-up word-by-word
captions and Instagram covers, in any number of caption styles (two ship: `buildup` and `brand`).
Also captions already-edited vertical videos (including iPhone HDR HLG) without re-cutting them.

Requirements: macOS on Apple Silicon, ffmpeg + ffprobe on PATH (libx264; libx265 for HDR), swiftc
(Xcode command line tools), python3. Everything else is installed by `setup.sh`.

## Setup (once, idempotent)

```
scripts/setup.sh
```
Creates the venv at `~/.panel-to-reels/venv` (mlx-whisper, pillow, numpy), downloads fonts into
`fonts/`, compiles `bin/faces`, downloads `bin/yt-dlp`, and prints a checklist ending in `READY`.
Override the venv home with `PANEL_TO_REELS_HOME=/some/dir`.

Run every step through the wrapper (it uses the venv python with `PYTHONNOUSERSITE=1`):
```
scripts/run.sh <step> <project-dir> [args...]
```
Steps: `fetch transcribe peek shots build captions cover render_all`.

## Project dir

Every step takes a project dir `P` first. Make one per event or video.

| path | written by | what |
|---|---|---|
| `P/source.<ext>` | fetch.py, or copy it in | the long video (`source.mkv`, `.mp4`, `.mov`, `.m4v`, `.webm`) |
| `P/transcript.json` | transcribe.py | `{"words": [{"i", "w", "s", "e"}], "segments": [...]}`: one global deduped word list, `i` = index |
| `P/transcript.txt` | transcribe.py | one line per segment: `[mm:ss] #<first word index> text` |
| `P/clips.json` | you | the clips to make (schema below) |
| `P/styles.json` | you, optional | style presets; falls back to the skill's `styles.json` |
| `P/shots.json` | shots.py | detected shots and faces per clip |
| `P/base/` | build.py, transcribe.py --file | `<clip>.mp4` vertical cut, `<clip>.words.json` clip-time words |
| `P/out/` | captions.py | `<clip>_<style>.mp4` |
| `P/covers/` | cover.py | `<clip>_<style>.jpg` |
| `P/frames/`, `P/sheets/` | build/shots/peek | tracking frames, contact sheets |
| `P/export/<Style label>/` | render_all.py | `NN - Title (Speaker).mp4` and `NN - Title (Speaker) - Cover.jpg` |

## Workflow A: long panel video

```
scripts/run.sh fetch P "https://www.youtube.com/watch?v=..." [--section 676-765]
scripts/run.sh transcribe P --prompt "Speaker Names, Company, jargon"
#   read P/transcript.txt, pick spans by word index (#N at the start of each line)
#   write P/clips.json with spans (+ title, speaker, headline, accent)
scripts/run.sh shots P A B C
#   prints shots per clip with face x centers (left to right) and a framing template;
#   look at P/sheets/shots_<clip>.jpg; set framing x to the speaker's face
scripts/run.sh peek P 11:20 12:40        # optional: contact sheet to see who is on camera
scripts/run.sh render_all P              # build + captions + covers + export + verify
```
Notes:
- `--section START-END` downloads only that part; all transcript times are then relative to the
  downloaded file (yt-dlp starts on a keyframe, so the file can begin a few seconds before START).
- Re-run a single stage while tuning: `build P A`, `captions P A buildup`, `cover P A brand`.
- `render_all` builds a base video only when `P/base/<clip>.mp4` is missing. After changing spans or
  framing, run `build P A` or `render_all P --rebuild`. Captions and covers are always re-rendered.

## Workflow B: already-edited vertical video (talking head, iPhone HDR)

```
scripts/run.sh transcribe P --file "/path/to/edited.mov" --clip S4
#   writes P/base/S4.words.json + P/base/S4.words.txt (indices for fix/emphasis) and links the file
#   as P/base/S4.mov. The source file itself is never modified.
#   add clip S4 to clips.json with "source_file": "/path/to/edited.mov"
scripts/run.sh render_all P --clips S4
```
No cutting or reframing. HLG input (`color_transfer=arib-std-b67`) stays HDR: captions are converted
to BT.2020 HLG and the output is HEVC Main10 `yuv420p10le` tagged bt2020/arib-std-b67 (needs libx265).
If the video is not 1080x1920 it is scaled and center-cropped to fill 1080x1920.
`render_all` runs the `transcribe --file` step itself when the words or link are missing.

## clips.json

```jsonc
{"clips": {
  "A": {
    "title": "Your Website Has Two Jobs",       // export file name; default = clip id
    "speaker": "Micah Burgess",                  // export file name "(Speaker)"; optional
    "spans": [[2246, 2493]],                     // inclusive word-index ranges from transcript.json; cut on word boundaries
    "fix": {"2655": "So", "7719": ""},           // word index -> caption text; "" removes the word from the captions
    "framing": [                                 // one mark per shot; "from" = absolute source seconds
      {"from": 0, "x": 0.77, "crop": 0.62},      // x = speaker face center 0..1 across the 16:9 frame
      {"from": 3617.2, "mode": "letterbox"}      // wide/reaction shot: full frame over a blurred fill
    ],                                           // crop = crop height as a fraction of source height (default 0.62)
    "emphasis": [2251, 2267],                    // optional hand-picked emphasis words; auto-emphasis fills pages with none
    "headline": "YOUR WEBSITE HAS *TWO JOBS.*",  // cover headline; *...* = accent words (they start their own line)
    "accent": "gold",                            // name from the style's cover.accents, or [r, g, b]
    "cover_time": 15,                            // seconds into the finished clip for the cover still (default: 1/3 in)
    "cover_shift": 0,                            // px to slide the photo up so the face clears the headline
    "caption_center": 1215,                      // optional caption block center, px from top (~1430 for selfie framing)
    "lockup": ["MICAH BURGESS", "SUMMIT OAK AI"],// optional per-clip override of the style's cover lockup
    "source_file": null                          // optional: already-edited vertical video (workflow B)
  }
}}
```
Framing rules (build.py): each span is cut at `W[a].s - 0.12` to `W[b].e + 0.22` (clamped before
the next word). A span is split into pieces at framing marks that fall inside it, ignoring marks
within 0.3s of either end; each piece uses the last mark at or before its start. The speaker's face
is tracked at 4 fps (only faces within 0.14 of the hinted x), smoothed, with jump-zooms (0.84x)
on sentence starts at most every ~4s. Audio comes from the source and is loudness-normalized to
-14 LUFS. In clips.json `"fix"` keys are strings; `"spans"` and `"emphasis"` are integers.

For workflow B clips, `fix` and `emphasis` indices refer to `P/base/<clip>.words.txt`, not the
project transcript.

## styles.json

Any number of presets; each has a `caption` block and a `cover` block. Fonts are file names in the
skill's `fonts/` dir; `"Sora:ExtraBold"` picks a named instance of a variable font (`Sora.ttf`).

```jsonc
{"mystyle": {
  "label": "My Style",                          // export folder name (default: style key, title-cased)
  "caption": {
    "font": "Poppins-SemiBold.ttf", "size": 54,          // normal words
    "emph_font": "Poppins-ExtraBold.ttf", "emph_size": 80, // emphasis words
    "colors": [[232, 56, 79], [45, 107, 255]],           // live highlight + emphasis color, cycling per page
    "gradient": null,                                    // or [[r,g,b], ...]: gradient fill instead of colors
    "pill": [11, 11, 13, 210],                           // dark pill behind pages over bright backgrounds
    "text": [255, 255, 255],                             // optional: color of words that are not lit
    "plate": null,                                       // or {"fill": [r,g,b], "text": [r,g,b], "pad": 16}: emphasis
                                                         // words sit on a solid label instead of being colored
    "upper": false                                       // true sets captions in caps
  },
  "cover": {
    "headline_font": "Anton-Regular.ttf", "lockup_font": "Poppins-SemiBold.ttf",
    "accents": {"gold": [236, 178, 52]},        // solid accent per clip (clip "accent" picks one)
    "tints":   {"gold": [20, 15, 6]},           // bottom tint matching each accent
    "gradient": null,                           // or [[r,g,b], ...]: accent words + rule use this gradient
    "tint": [11, 11, 13],                       // tint when the accent has none in tints
    "bloom": {"color": [60, 18, 90], "strength": 0.45},  // optional glow behind the headline
    "lockup": ["YOUR NAME", "YOUR EVENT"],      // letterspaced lines under the rule ([] for none)
    "separator": "×", "separator_color": "accent",  // or [r, g, b]
    "plate": null                               // or {"fill": [r,g,b], "text": [r,g,b]}: accent lines on a solid bar
  },
  "grade": null                                 // optional ffmpeg filter chain for the video and cover still,
}}                                              // e.g. "hue=s=0,curves=..." for black and white
```
Shipped presets: `buildup` (Poppins, red/blue/magenta per page, gold/red/blue cover accents) and
`brand` (Sora, coral/magenta/violet gradient, dark tint + violet bloom). `examples/summit-oak-styles.json`
is the same pair with Summit Oak lockups; copy it to `P/styles.json` to use it.
`examples/mono-styles.json` shows a monochrome look built from these options: a black and white `grade`,
Inter caps, and emphasis words on a white `plate` (plus a color variant with one red accent).

## Step reference

| step | usage | output |
|---|---|---|
| fetch | `fetch.py P URL [--section START-END] [--force]` | `P/source.mkv`, `P/source.json` (best video <= 2160p + best audio) |
| transcribe | `transcribe.py P [--prompt TEXT] [--language en]` | `P/transcript.json`, `P/transcript.txt` |
| transcribe (solo) | `transcribe.py P --file VIDEO --clip ID` | `P/base/ID.words.json/.words.txt`, link `P/base/ID.<ext>` |
| peek | `peek.py P START END [N=12]` | `P/sheets/peek_<START>.jpg` |
| shots | `shots.py P CLIP...` | `P/shots.json`, `P/sheets/shots_<CLIP>.jpg`, face x printout |
| build | `build.py P [CLIP...]` | `P/base/CLIP.mp4`, `P/base/CLIP.words.json` (skips source_file clips) |
| captions | `captions.py P CLIP STYLE` | `P/out/CLIP_STYLE.mp4` |
| cover | `cover.py P CLIP STYLE` | `P/covers/CLIP_STYLE.jpg` |
| render_all | `render_all.py P [--clips A,B] [--styles buildup,brand] [--rebuild]` | everything + `P/export/...` + report |

Times for peek and `--section` accept seconds (`681.5`) or `mm:ss` / `h:mm:ss`.

## Checking output

- `render_all` ends with a table: size, codec, pix_fmt, transfer, audio, duration, OK/CHECK. It exits
  non-zero and prints the failing step's output when anything fails.
- Look at frames before posting. For HDR files use `hlg.frame(path, t)` (tone-mapped), not a raw
  ffmpeg grab, which looks washed out:
  ```
  PYTHONNOUSERSITE=1 ~/.panel-to-reels/venv/bin/python -s -c "import sys; sys.path.insert(0, 'scripts'); \
    import hlg; hlg.frame('P/out/A_brand.mp4', 12).save('/tmp/check.jpg')"
  ```
- Check every number and name in captions and headlines against the transcript before export;
  use `fix` for whisper mishearings (e.g. names, "ChatGPT").

## Gotchas

- Always run Python through `run.sh` (or `PYTHONNOUSERSITE=1 <venv>/bin/python -s`): user
  site-packages on this machine can hold broken x86 wheels.
- An x86 ffmpeg under Rosetta works but `hevc_videotoolbox` fails there; HDR output uses libx265.
- The ffmpeg used needs `sendcmd`, `loudnorm`, `vignette`; drawtext is not needed (all text is PIL).
- YouTube downloads need a JS runtime: fetch.py passes node to yt-dlp when deno is not installed.
- `/private/tmp` is purged by macOS after a few days; keep projects somewhere durable.
