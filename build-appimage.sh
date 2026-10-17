#!/bin/sh
# Build the ShortCut Linux AppImage.
#
# Layout inside the AppDir:
#   usr/python/            standalone CPython 3.12 (relocatable, uv-managed)
#   usr/lib/site-packages/ pip deps (faster-whisper, yt-dlp, Pillow, ...)
#   usr/lib/shortscut/     the app package
#   usr/bin/ffmpeg, ffprobe (static builds, GPL — see README)
#   usr/share/fonts/       DejaVuSans-Bold (bundled so captions always render)
#   AppRun                 launcher (GUI by default, --cli for headless)
#
# Usage: ./build-appimage.sh [output-AppImage-path]
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
# Durable scratch under ~/workspace/tmp (NOT /tmp — this VM's /tmp is
# ephemeral and a restart mid-build wipes it). Override with env if needed.
BUILD="${SHORTSCUT_BUILD_DIR:-$HOME/workspace/tmp/shortscut-appimage-build}"
APPDIR="$BUILD/AppDir"
OUT="${1:-$ROOT/ShortCut-Linux-x86_64.AppImage}"

echo "== build dir: $BUILD"
rm -rf "$BUILD"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/fonts" \
         "$APPDIR/usr/share/fontconfig"

# ---- appimagetool (extracted, so no FUSE is needed) ----
if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="$(command -v appimagetool)"
else
    echo "== fetching appimagetool"
    curl -sL --max-time 120 -o "$BUILD/appimagetool.AppImage" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$BUILD/appimagetool.AppImage"
    (cd "$BUILD" && ./appimagetool.AppImage --appimage-extract >/dev/null)
    APPIMAGETOOL="$BUILD/squashfs-root/AppRun"
fi

# ---- standalone Python 3.12 ----
echo "== installing standalone Python 3.12"
UV="${UV:-$HOME/.local/bin/uv}"
if [ ! -x "$UV" ]; then UV="uv"; fi
"$UV" python install 3.12 --install-dir "$APPDIR/usr/python" >/dev/null
PYBIN="$(find "$APPDIR/usr/python" -name "python3.12" -type f | head -n 1)"
[ -n "$PYBIN" ] || { echo "ERROR: no python3.12 found in $APPDIR/usr/python"; exit 1; }
PYREL="${PYBIN#$APPDIR/}"
echo "== python: $PYREL"
"$PYBIN" -c "import tkinter" || { echo "ERROR: this Python has no tkinter (GUI needs it)"; exit 1; }

# ---- pip deps into AppDir (no venv — AppRun sets PYTHONPATH) ----
# --only-binary: a missing wheel must fail loudly, not silently fall back
# to a source build (av 14.4.0 did exactly that — no wheel, needs libav).
echo "== installing pip deps"
"$UV" pip install --python "$PYBIN" --target "$APPDIR/usr/lib/site-packages" \
    --only-binary :all: -r "$ROOT/requirements.txt" -q

# ---- app code ----
cp -r "$ROOT/shortscut" "$APPDIR/usr/lib/shortscut"
find "$APPDIR/usr/lib/shortscut" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# ---- static ffmpeg / ffprobe (johnvansickle.com, GPL) ----
echo "== fetching static ffmpeg"
curl -sL --max-time 300 -o "$BUILD/ffmpeg-static.tar.xz" \
    https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
# --no-same-owner: the tarball stores uid/gid 1000; this VM's sandbox
# cannot chown, so tar fails unless ownership is dropped on extract.
tar --no-same-owner --no-same-permissions -xJf "$BUILD/ffmpeg-static.tar.xz" -C "$BUILD"
FFDIR="$(find "$BUILD" -maxdepth 1 -name "ffmpeg-*-amd64-static" -type d | head -n 1)"
cp "$FFDIR/ffmpeg" "$FFDIR/ffprobe" "$APPDIR/usr/bin/"
chmod +x "$APPDIR/usr/bin/ffmpeg" "$APPDIR/usr/bin/ffprobe"

# ---- caption font (DejaVu Sans Bold, bundled so captions always render) ----
if [ -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ]; then
    cp /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf "$APPDIR/usr/share/fonts/"
else
    echo "ERROR: DejaVuSans-Bold.ttf not found on this machine — install fonts-dejavu-core"
    exit 1
fi

# ---- fontconfig template (AppRun fills in @HERE@ at runtime) ----
cat > "$APPDIR/usr/share/fontconfig/fonts.conf.template" <<'EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>@HERE@/usr/share/fonts</dir>
  <dir>/usr/share/fonts</dir>
  <dir>/usr/local/share/fonts</dir>
  <dir prefix="xdg">fonts</dir>
  <cachedir>~/.cache/fontconfig</cachedir>
</fontconfig>
EOF

# ---- desktop file + icon ----
cp "$ROOT/shortscut.desktop" "$APPDIR/"
"$UV" run --python "$PYBIN" --with Pillow "$ROOT/assets/make_icon.py" >/dev/null 2>&1 \
    || (cd "$ROOT" && "$PYBIN" assets/make_icon.py)
cp "$ROOT/assets/shortscut.png" "$APPDIR/shortscut.png"
ln -sf shortscut.png "$APPDIR/.DirIcon"

# ---- AppRun ----
cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
# ShortCut launcher: GUI by default, --cli for headless runs.
set -e
HERE="\$(dirname "\$(readlink -f "\$0")")"
export PATH="\$HERE/usr/bin:\$PATH"
if [ -z "\${SSL_CERT_FILE:-}" ] && [ -f /etc/ssl/certs/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
if [ -z "\${REQUESTS_CA_BUNDLE:-}" ] && [ -f /etc/ssl/certs/ca-certificates.crt ]; then
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
fi
FC_TMP="\$HOME/.cache/shortscut/fonts.conf"
mkdir -p "\$(dirname "\$FC_TMP")"
sed "s|@HERE@|\$HERE|g" "\$HERE/usr/share/fontconfig/fonts.conf.template" > "\$FC_TMP"
export FONTCONFIG_FILE="\$FC_TMP"
export PYTHONPATH="\$HERE/usr/lib/site-packages:\$HERE/usr/lib"
export PYTHONNOUSERSITE=1
PY="\$HERE/$PYREL"
if [ "\${1:-}" = "--cli" ]; then shift; exec "\$PY" -m shortscut.cli "\$@"; else exec "\$PY" -m shortscut "\$@"; fi
EOF
chmod +x "$APPDIR/AppRun"

# ---- build ----
echo "== building $OUT"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$OUT" >/dev/null
ls -la "$OUT"
echo "== done"
