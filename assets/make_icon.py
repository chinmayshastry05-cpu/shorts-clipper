"""Generate the ShortCut icon (original artwork, drawn with Pillow).

A dark rounded square, a white 9:16 phone outline, a play triangle, and a
caption bar — the app in one glyph. No third-party assets.
"""

from pathlib import Path

from PIL import Image, ImageDraw


def main():
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Dark rounded-square background
    d.rounded_rectangle([4, 4, size - 4, size - 4], radius=48, fill=(17, 17, 17, 255))
    # Phone outline (9:16-ish, centered)
    x0, y0, x1, y1 = 88, 36, 168, 220
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, outline=(255, 255, 255, 255), width=6)
    # Play triangle
    d.polygon([(112, 96), (112, 148), (154, 122)], fill=(255, 215, 64, 255))
    # Caption bar (the draggable caption)
    d.rounded_rectangle([102, 168, 154, 184], radius=6, fill=(255, 255, 255, 255))
    d.rounded_rectangle([108, 190, 148, 198], radius=4, fill=(136, 136, 136, 255))
    out = Path(__file__).resolve().parent / "shortscut.png"
    img.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
