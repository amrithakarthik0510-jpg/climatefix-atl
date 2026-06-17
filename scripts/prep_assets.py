"""
Make the landing PNG backgrounds transparent. Auto-detects whether each file is
on a WHITE or BLACK background (from its corners) and keys that color out.
Orbs get a soft glow alpha; figures/text/arc get a harder cut-out.
Files that are already transparent are left alone.

    pip install pillow numpy
    python3 scripts/prep_assets.py
"""

from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "frontend" / "assets"
ORBS = {"orb-pink", "orb-orange", "orb-yellow", "route"}   # glows: soft alpha
SOLID = {"arc", "figure-man", "figure-woman", "figure-coat", "text-walkit", "text-atl"}


def main():
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        raise SystemExit("Run:  pip install pillow numpy")

    for name in ORBS | SOLID:
        p = ASSETS / f"{name}.png"
        if not p.exists():
            print(f"  (skip) {name}.png not found"); continue
        im = Image.open(p).convert("RGBA")
        a = np.array(im).astype(np.float32)
        r, g, b, oa = a[..., 0], a[..., 1], a[..., 2], a[..., 3]

        if (oa == 0).mean() > 0.25:
            print(f"  · {name}.png already transparent — left as is"); continue

        # background colour from the 4 corners
        cor = np.array([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]])
        lum = (0.299 * cor[:, 0] + 0.587 * cor[:, 1] + 0.114 * cor[:, 2]).mean()
        soft = name in ORBS

        if lum < 60:   # black background
            base = np.maximum(np.maximum(r, g), b)
            tag = "black"
        else:          # white / light background
            base = 255.0 - np.minimum(np.minimum(r, g), b)
            tag = "white"
        gain = 1.2 if soft else 2.4
        a[..., 3] = np.clip(base * gain, 0, 255) * (oa / 255.0)
        Image.fromarray(a.astype("uint8"), "RGBA").save(p)
        print(f"  ✓ {name}.png — {tag} removed")

    print("\nDone. Refresh the resident page.")


if __name__ == "__main__":
    main()
