# Panel to Reels

A Claude Code skill that turns one long panel, talk or podcast into a batch of vertical reels: cut on word boundaries, reframed to 9:16 around the speaker's face, captioned word by word, with a cover for every reel built for the Instagram profile grid. Every clip renders in two caption styles, and the second one uses your own fonts and colors.

We used it to turn an 87-minute AI panel into 18 clips in two styles: 36 reels, each with a cover and post copy.

## Install

```bash
brew install ffmpeg
git clone https://github.com/micahwburgess-spec/panel-to-reels ~/.claude/skills/panel-to-reels
bash ~/.claude/skills/panel-to-reels/scripts/setup.sh
```

Then open Claude Code and ask:

```
Use the panel-to-reels skill on this video: [paste link]
```

## Requirements

- A Mac with Apple Silicon (M1 or newer). Face tracking uses Apple Vision and transcription runs locally with mlx-whisper.
- Claude Code.
- ffmpeg with libx264 and libx265.
- A few GB of free disk for a 4K source.

## What's inside

- `SKILL.md` is the workflow Claude follows, including the judgment calls: picking moments, checking who's on camera, cutting on word boundaries, writing honest headlines.
- `scripts/` holds the pipeline. `scripts/USAGE.md` documents every command.
- `styles.json` holds the two caption and cover presets. `examples/` shows a fully branded setup and a sample `clips.json`.

Built by Micah Burgess, Summit Oak AI. [summitoakai.com](https://summitoakai.com)
