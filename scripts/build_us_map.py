"""Turn the us-atlas TopoJSON into plain SVG paths the dashboard can draw.

Why this exists rather than a charting library at runtime: the map never
changes, so there is no reason to ship a projection engine to the browser and
re-run it on every page load. This script does the work once and writes a small
JSON file of finished `<path d="...">` strings. The dashboard then needs no
mapping library, no CDN, and works offline.

Source data
-----------
us-atlas (https://github.com/topojson/us-atlas), ISC licensed, built from US
Census Bureau cartographic boundary files, which are in the public domain. The
`states-albers-10m` build is already projected to Albers USA - the standard
projection for US thematic maps, with Alaska and Hawaii repositioned as insets
so the lower 48 stay legible.

Usage
-----
    python scripts/build_us_map.py [path/to/states-albers-10m.json]

Download the input with:
    curl -sSL -o var/tmp/states-albers-10m.json \\
      https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tt.extract.locations import STATES  # noqa: E402

SOURCE_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json"
OUTPUT = ROOT / "tt" / "web" / "static" / "us-states.json"
PRECISION = 1


def decode_arcs(topology: dict) -> list[list[tuple[float, float]]]:
    """Undo TopoJSON's delta encoding to get absolute coordinates.

    Each arc stores its first point in full and every later point as an offset
    from the one before it, which is what makes the file small.
    """
    transform = topology.get("transform")
    arcs: list[list[tuple[float, float]]] = []
    for arc in topology["arcs"]:
        points: list[tuple[float, float]] = []
        x = y = 0.0
        for index, point in enumerate(arc):
            if transform:
                x += point[0]
                y += point[1]
                sx, sy = transform["scale"]
                tx, ty = transform["translate"]
                points.append((x * sx + tx, y * sy + ty))
            else:
                points.append((point[0], point[1]))
            del index
        arcs.append(points)
    return arcs


def ring_points(arc_indexes, arcs) -> list[tuple[float, float]]:
    """Stitch a closed ring together from the arcs it is made of.

    A negative index means "this arc, walked backwards" - shared borders are
    stored once and reused by both neighbours.
    """
    points: list[tuple[float, float]] = []
    for index in arc_indexes:
        arc = arcs[~index][::-1] if index < 0 else arcs[index]
        points.extend(arc[1:] if points else arc)
    return points


def to_path(points_list: list[list[tuple[float, float]]]) -> str:
    parts = []
    for points in points_list:
        if len(points) < 3:
            continue
        coords = [f"{round(x, PRECISION)},{round(y, PRECISION)}" for x, y in points]
        parts.append("M" + "L".join(coords) + "Z")
    return "".join(parts)


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Shoelace formula. Used to pick the biggest piece of a state."""
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    area = polygon_area(points)
    if area < 1e-9:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    cx = cy = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    signed = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        signed += x1 * y2 - x2 * y1
    signed /= 2
    if abs(signed) < 1e-9:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (6 * signed), cy / (6 * signed)


def build(source: Path | None = None) -> dict:
    if source and source.exists():
        topology = json.loads(source.read_text(encoding="utf-8"))
    else:
        print(f"downloading {SOURCE_URL}")
        with urllib.request.urlopen(SOURCE_URL, timeout=90) as response:
            topology = json.loads(response.read())

    arcs = decode_arcs(topology)
    name_to_abbr = {name.lower(): abbr for name, abbr in STATES.items()}

    states = []
    for geometry in topology["objects"]["states"]["geometries"]:
        name = (geometry.get("properties") or {}).get("name", "")
        abbr = name_to_abbr.get(name.lower())
        if not abbr:
            print(f"  skipping {name!r} - no two-letter code")
            continue

        if geometry["type"] == "Polygon":
            polygons = [geometry["arcs"]]
        elif geometry["type"] == "MultiPolygon":
            polygons = geometry["arcs"]
        else:
            continue

        rings: list[list[tuple[float, float]]] = []
        biggest: list[tuple[float, float]] = []
        biggest_area = 0.0
        for polygon in polygons:
            for ring_index, arc_indexes in enumerate(polygon):
                points = ring_points(arc_indexes, arcs)
                rings.append(points)
                if ring_index == 0:  # outer ring
                    area = polygon_area(points)
                    if area > biggest_area:
                        biggest_area, biggest = area, points

        cx, cy = centroid(biggest) if biggest else (0.0, 0.0)
        states.append({
            "abbr": abbr,
            "name": name,
            "d": to_path(rings),
            "cx": round(cx, 1),
            "cy": round(cy, 1),
            "area": round(biggest_area),
        })

    states.sort(key=lambda s: s["abbr"])
    bbox = topology.get("bbox") or [0, 0, 975, 610]
    return {
        "viewBox": "0 0 975 610",
        "bbox": [round(v, 1) for v in bbox],
        "source": "us-atlas (ISC) / US Census Bureau cartographic boundaries (public domain)",
        "projection": "Albers USA, pre-projected; Alaska and Hawaii shown as insets",
        "states": states,
    }


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "var" / "tmp" / "states-albers-10m.json"
    data = build(source)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"wrote {OUTPUT.relative_to(ROOT)} - {len(data['states'])} states, {size_kb:.0f} KB")
    missing = {a for a in STATES.values()} - {s["abbr"] for s in data["states"]}
    if missing:
        print(f"note: no shape for {sorted(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
