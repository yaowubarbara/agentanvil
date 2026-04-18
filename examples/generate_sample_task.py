"""
Generate one hand-synthesized Jordan Count task for the walking skeleton.

Why it lives under examples/ and not in the package:
  The upstream benchmark (github.com/yaowubarbara/jordan-count) owns task
  generation. This script creates a *placeholder* task sufficient to exercise
  the pipeline end-to-end without pulling in shapely / scipy / the upstream
  generator yet. Phase 1 replaces it with a loader that reads the upstream
  JSON dump so evaluation numbers are directly comparable.

Gold is computed by ray casting (crossing number) against a polygon.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def _polygon_rose(cx: float, cy: float, r: float, k: int = 3, n: int = 256) -> list[tuple[float, float]]:
    """A k-petal rose curve, sampled as a polygon. Gives a non-convex closed region."""
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        rr = r * (0.7 + 0.3 * math.cos(k * theta))
        pts.append((cx + rr * math.cos(theta), cy + rr * math.sin(theta)))
    pts.append(pts[0])
    return pts


def _point_in_polygon(p: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = p
    inside = False
    n = len(poly) - 1
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[i + 1]
        if (y1 > y) != (y2 > y):
            xi = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
            if x < xi:
                inside = not inside
    return inside


def _try_render_png(path: Path, poly, dots):
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError:
        return False
    W = H = 512
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    scaled_poly = [(x, H - y) for x, y in poly]
    draw.line(scaled_poly, fill="black", width=3)
    for idx, (x, y) in enumerate(dots, 1):
        sx, sy = x, H - y
        draw.ellipse((sx - 6, sy - 6, sx + 6, sy + 6), fill="red", outline="black")
        draw.text((sx + 8, sy - 6), str(idx), fill="black")
    img.save(path)
    return True


def main():
    out_dir = Path(__file__).parent / "sample_tasks"
    out_dir.mkdir(exist_ok=True)

    poly = _polygon_rose(256, 256, 180, k=3)
    dots = [
        (256, 256),   # center — inside
        (256, 440),   # top — outside the petal boundary in most rotations
        (120, 256),   # left petal — inside
        (440, 256),   # right petal — inside
        (256, 60),    # bottom — outside
        (90, 90),     # corner — outside
        (422, 422),   # corner — outside
        (200, 330),   # boundary region — test case
    ]
    gold = sum(1 for p in dots if _point_in_polygon(p, poly))

    task_id = "task_000"
    png_path = out_dir / f"{task_id}.png"
    rendered = _try_render_png(png_path, poly, dots)

    task = {
        "task_id": task_id,
        "image_path": str(png_path) if rendered else None,
        "dots": dots,
        "curve_points": poly,
        "gold_count": gold,
        "source": "hand-synthesized (examples/generate_sample_task.py)",
    }
    (out_dir / f"{task_id}.json").write_text(json.dumps(task, indent=2))
    print(f"Wrote {out_dir / f'{task_id}.json'}  gold_count={gold}  image={'✓' if rendered else '✗ (pip install pillow to render)'}")


if __name__ == "__main__":
    main()
