#!/bin/bash
# One-time (idempotent) setup for panel-to-reels.
#
# Usage: scripts/setup.sh
#
# - checks macOS on Apple Silicon, ffmpeg/ffprobe (and libx265 for HDR output), swiftc
# - creates the Python venv in ~/.panel-to-reels/venv (durable; /private/tmp gets purged)
#   and installs mlx-whisper, pillow, numpy
# - downloads the OFL fonts into <skill>/fonts/
# - compiles scripts/faces.swift to <skill>/bin/faces (Apple Vision face detector)
# - downloads the standalone yt-dlp macOS binary to <skill>/bin/yt-dlp
# Safe to run again: anything already in place is kept.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$(dirname "$HERE")"
HOMEDIR="${PANEL_TO_REELS_HOME:-$HOME/.panel-to-reels}"
VENV="$HOMEDIR/venv"
BIN="$SKILL/bin"
FONTS="$SKILL/fonts"
OK=(); BAD=()
ok()  { OK+=("$1"); echo "  ok    $1"; }
bad() { BAD+=("$1"); echo "  FAIL  $1"; }

echo "panel-to-reels setup"
echo "  skill: $SKILL"
echo "  venv:  $VENV"

# 1. platform
if [ "$(uname -s)" != "Darwin" ]; then bad "macOS required (found $(uname -s))"; fi
if [ "$(uname -m)" = "arm64" ] || [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
  ok "Apple Silicon"
else
  bad "Apple Silicon required (mlx-whisper runs on the Apple GPU)"
fi

# 2. ffmpeg
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "ffmpeg at $(command -v ffmpeg)"
  ENC="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
  echo "$ENC" | grep -q libx264 && ok "libx264 encoder" || bad "ffmpeg has no libx264 (needed for every SDR render)"
  if echo "$ENC" | grep -q libx265; then
    ok "libx265 encoder (HDR HLG output)"
  else
    echo "  WARN  ffmpeg has no libx265: iPhone HDR (HLG) source_file clips will fail in captions.py."
    echo "        Install a full build, e.g. 'brew install ffmpeg', and re-run."
  fi
  FIL="$(ffmpeg -hide_banner -filters 2>/dev/null)"
  for f in sendcmd loudnorm vignette; do
    echo "$FIL" | grep -q " $f " && ok "ffmpeg filter $f" || bad "ffmpeg filter $f missing"
  done
else
  bad "ffmpeg/ffprobe not on PATH (brew install ffmpeg)"
fi

# 3. venv
PY=""
for c in python3.13 python3.12 python3.11 python3.10 /usr/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
mkdir -p "$HOMEDIR"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; then
  if [ -z "$PY" ]; then
    bad "no python3 found"
  else
    echo "  ...   creating venv with $PY"
    rm -rf "$VENV"
    arch -arm64 "$PY" -m venv "$VENV" || "$PY" -m venv "$VENV"
  fi
fi
if [ -x "$VENV/bin/python" ]; then
  VPY=(env PYTHONNOUSERSITE=1 arch -arm64 "$VENV/bin/python" -s)
  if ! "${VPY[@]}" -c "import mlx_whisper, PIL, numpy" >/dev/null 2>&1; then
    echo "  ...   installing mlx-whisper pillow numpy (a few minutes the first time)"
    "${VPY[@]}" -m pip install -q --upgrade pip >/dev/null 2>&1
    "${VPY[@]}" -m pip install -q mlx-whisper pillow numpy
  fi
  "${VPY[@]}" -c "import mlx_whisper, PIL, numpy" >/dev/null 2>&1 \
    && ok "venv python packages (mlx-whisper, pillow, numpy)" \
    || bad "venv packages failed to import (try: rm -rf $VENV and re-run)"
fi

# 4. fonts (SIL Open Font License, from github.com/google/fonts)
mkdir -p "$FONTS"
RAW="https://raw.githubusercontent.com/google/fonts/main/ofl"
fetch_font() {   # $1 = repo path, $2 = local name
  if [ ! -s "$FONTS/$2" ]; then
    curl -fsSL "$RAW/$1" -o "$FONTS/$2.part" && mv "$FONTS/$2.part" "$FONTS/$2"
  fi
  [ -s "$FONTS/$2" ] && ok "font $2" || bad "font $2 (download failed)"
}
fetch_font "anton/Anton-Regular.ttf" "Anton-Regular.ttf"
fetch_font "poppins/Poppins-SemiBold.ttf" "Poppins-SemiBold.ttf"
fetch_font "poppins/Poppins-ExtraBold.ttf" "Poppins-ExtraBold.ttf"
fetch_font "sora/Sora%5Bwght%5D.ttf" "Sora.ttf"

# 5. face detector
mkdir -p "$BIN"
if [ ! -x "$BIN/faces" ] || [ "$HERE/faces.swift" -nt "$BIN/faces" ]; then
  if command -v swiftc >/dev/null; then
    echo "  ...   compiling faces.swift"
    swiftc -O "$HERE/faces.swift" -o "$BIN/faces" 2>&1 | tail -5
  fi
fi
[ -x "$BIN/faces" ] && ok "bin/faces (Vision face detector)" || bad "bin/faces (needs swiftc: xcode-select --install)"

# 6. yt-dlp
if [ ! -x "$BIN/yt-dlp" ]; then
  echo "  ...   downloading yt-dlp"
  curl -fsSL "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos" -o "$BIN/yt-dlp.part" \
    && mv "$BIN/yt-dlp.part" "$BIN/yt-dlp" && chmod +x "$BIN/yt-dlp"
fi
if [ -x "$BIN/yt-dlp" ] && "$BIN/yt-dlp" --version >/dev/null 2>&1; then
  ok "bin/yt-dlp $("$BIN/yt-dlp" --version)"
else
  bad "bin/yt-dlp (download failed)"
fi
command -v deno >/dev/null || command -v node >/dev/null \
  && ok "JS runtime for YouTube ($(command -v deno || command -v node))" \
  || echo "  WARN  no deno/node on PATH: yt-dlp may fail on some YouTube videos (brew install deno)"

echo
if [ ${#BAD[@]} -eq 0 ]; then
  echo "READY. Run steps with: $HERE/run.sh <step> <project-dir> ..."
  exit 0
else
  echo "NOT READY. Fix these and re-run setup.sh:"
  for b in "${BAD[@]}"; do echo "  - $b"; done
  exit 1
fi
