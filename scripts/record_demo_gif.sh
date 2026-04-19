#!/usr/bin/env bash
# Record the AgentAnvil dashboard as a small, palette-optimized GIF.
#
# Intended use: commit docs/dashboard.gif to the repo so the README auto-displays
# it. Target size: under 3 MB so GitHub README renders without warning.
#
# Prereqs (one-time):
#   sudo apt-get install -y ffmpeg x11-utils    # Linux / WSL
#   # macOS:  brew install ffmpeg
#   # Windows (WSL2):  install XServer or record from the Windows side with OBS
#
# Flow:
#   1. Start the dev server in another terminal:  (cd ui && npm run dev)
#   2. Open http://localhost:3001 in a real browser window (not maximized)
#   3. Run this script; it:
#        a. Captures 10 seconds of a 1280×720 region at (x=0,y=0)
#        b. Generates an optimized 256-color palette from the clip
#        c. Re-encodes with that palette into a ~2-3 MB GIF
#   4. The GIF lands at docs/dashboard.gif; commit it.
#
# Tune the values if your setup differs:
#   OFFSET_X / OFFSET_Y   — top-left corner of the browser window
#   WIDTH / HEIGHT        — capture region (keep 16:9 for good GIF framing)
#   DURATION_SECONDS      — 8-12s is the sweet spot
#   FPS                   — 12 looks fluid, 8 saves bytes
set -euo pipefail

OFFSET_X="${OFFSET_X:-0}"
OFFSET_Y="${OFFSET_Y:-80}"
WIDTH="${WIDTH:-1280}"
HEIGHT="${HEIGHT:-720}"
DURATION_SECONDS="${DURATION_SECONDS:-10}"
FPS="${FPS:-12}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/docs"
RAW="${OUT_DIR}/.dashboard-raw.mp4"
PALETTE="${OUT_DIR}/.dashboard-palette.png"
GIF="${OUT_DIR}/dashboard.gif"

mkdir -p "${OUT_DIR}"

echo "==> [1/3] capture ${WIDTH}x${HEIGHT} @ (${OFFSET_X},${OFFSET_Y}) for ${DURATION_SECONDS}s at ${FPS}fps"
echo "    (switch to your browser window now — capture starts in 3s)"
sleep 3

if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: use avfoundation
    ffmpeg -y -loglevel error -f avfoundation -framerate "${FPS}" -i "1" \
        -t "${DURATION_SECONDS}" -vf "crop=${WIDTH}:${HEIGHT}:${OFFSET_X}:${OFFSET_Y}" \
        -c:v libx264 -pix_fmt yuv420p "${RAW}"
else
    # Linux / WSL2 X server: use x11grab
    ffmpeg -y -loglevel error -f x11grab -framerate "${FPS}" \
        -video_size "${WIDTH}x${HEIGHT}" -i ":0.0+${OFFSET_X},${OFFSET_Y}" \
        -t "${DURATION_SECONDS}" -c:v libx264 -pix_fmt yuv420p "${RAW}"
fi

echo "==> [2/3] generate optimized palette"
ffmpeg -y -loglevel error -i "${RAW}" \
    -vf "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,palettegen=stats_mode=diff" \
    "${PALETTE}"

echo "==> [3/3] encode GIF with palette"
ffmpeg -y -loglevel error -i "${RAW}" -i "${PALETTE}" \
    -lavfi "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle" \
    "${GIF}"

# Clean up intermediate artifacts
rm -f "${RAW}" "${PALETTE}"

BYTES=$(stat -c%s "${GIF}" 2>/dev/null || stat -f%z "${GIF}")
MB=$(awk "BEGIN {printf \"%.2f\", ${BYTES}/1024/1024}")

echo ""
echo "==> done: ${GIF}  (${MB} MB)"
echo ""
if (( BYTES > 5242880 )); then
    echo "⚠ GIF is over 5 MB; lower FPS or WIDTH, or shorten DURATION_SECONDS."
elif (( BYTES > 3145728 )); then
    echo "ℹ GIF is over 3 MB — renders fine on GitHub but loads slower on mobile."
else
    echo "✓ Size is well under GitHub's comfortable README-inline threshold."
fi

echo ""
echo "Suggested demo script for the 10-second clip:"
echo "  t=0-2s   linger on Dashboard (metric cards, accuracy bar chart load)"
echo "  t=2-4s   hover over the Scaffold × Task heatmap to show tooltips"
echo "  t=4-6s   click a row in Recent Activity → navigate to /trace/<id>"
echo "  t=6-8s   click Play on the playback controls; watch the waterfall highlight"
echo "  t=8-10s  click 'all traces' breadcrumb → back to /traces filter bar"
