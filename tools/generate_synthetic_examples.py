from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scale: float) -> Vec2:
        return Vec2(self.x * scale, self.y * scale)

    def distance_to(self, other: Vec2) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class ReferenceArc:
    circle_id: int
    center: Vec2
    radius: float
    turn: str
    p_start: Vec2
    p_end: Vec2
    angle_rad: float
    length_cm: float


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("synthetic_dir", type=Path)
    parser.add_argument("--examples-dir", type=Path, default=Path("examples/synthetic"))
    parser.add_argument("--reference-dir", type=Path, default=Path("examples/synthetic_reference"))
    args = parser.parse_args()

    args.examples_dir.mkdir(parents=True, exist_ok=True)
    args.reference_dir.mkdir(parents=True, exist_ok=True)

    for csv_path in sorted(args.synthetic_dir.glob("*.csv")):
        course_name = csv_path.stem
        blocks = load_blocks(csv_path)
        course, helper_circles, reference_arcs, reference_tangents = build_reference_course(blocks)

        write_json(args.examples_dir / f"{course_name}.json", course)
        write_json(args.reference_dir / f"{course_name}_helper_circles.json", {"helper_circles": helper_circles})
        write_json(args.reference_dir / f"{course_name}_arcs.json", {"arcs": reference_arcs})
        write_json(args.reference_dir / f"{course_name}_tangents.json", {"tangents": reference_tangents})
        print(f"{course_name}: {len(helper_circles)} helper circles")

    return 0


def load_blocks(path: Path) -> list[tuple[float, float]]:
    blocks = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#"):
                continue
            blocks.append((float(row[0]), float(row[1])))
    return blocks


def build_reference_course(blocks: list[tuple[float, float]]):
    pos = Vec2(0.0, 0.0)
    theta = 0.0
    arcs: list[ReferenceArc] = []

    for length_m, curvature in blocks:
        start = pos
        end, next_theta = endpoint_after_block(pos, theta, length_m, curvature)

        if abs(curvature) > 1e-12:
            left = Vec2(-math.sin(theta), math.cos(theta))
            center = start + left * (100.0 / curvature)
            turn = "ccw" if curvature > 0 else "cw"
            radius = 100.0 / abs(curvature)
            angle_rad = abs(curvature * length_m)
            length_cm = length_m * 100.0

            if arcs and same_helper_circle(arcs[-1], center, radius, turn) and arcs[-1].p_end.distance_to(start) < 0.1:
                previous = arcs[-1]
                arcs[-1] = ReferenceArc(
                    circle_id=previous.circle_id,
                    center=previous.center,
                    radius=previous.radius,
                    turn=previous.turn,
                    p_start=previous.p_start,
                    p_end=end,
                    angle_rad=previous.angle_rad + angle_rad,
                    length_cm=previous.length_cm + length_cm,
                )
            else:
                arcs.append(
                    ReferenceArc(
                        circle_id=len(arcs),
                        center=center,
                        radius=radius,
                        turn=turn,
                        p_start=start,
                        p_end=end,
                        angle_rad=angle_rad,
                        length_cm=length_cm,
                    )
                )

        pos, theta = end, next_theta

    helper_circles = [
        {
            "id": arc.circle_id,
            "x": round_float(arc.center.x),
            "y": round_float(arc.center.y),
            "r": round_float(arc.radius),
            "turn": arc.turn,
        }
        for arc in arcs
    ]
    reference_arcs = [
        {
            "circle_id": arc.circle_id,
            "center": point_dict(arc.center),
            "radius": round_float(arc.radius),
            "turn": arc.turn,
            "p_start": point_dict(arc.p_start),
            "p_end": point_dict(arc.p_end),
            "angle_rad": round_float(arc.angle_rad),
            "length_cm": round_float(arc.length_cm),
        }
        for arc in arcs
    ]
    reference_tangents = []
    for i, arc in enumerate(arcs):
        next_arc = arcs[(i + 1) % len(arcs)]
        reference_tangents.append(
            {
                "from_circle_id": arc.circle_id,
                "to_circle_id": next_arc.circle_id,
                "p_from": point_dict(arc.p_end),
                "p_to": point_dict(next_arc.p_start),
                "length_cm": round_float(arc.p_end.distance_to(next_arc.p_start)),
            }
        )

    sg_center = (arcs[-1].p_end + arcs[0].p_start) * 0.5
    course = {
        "board": {
            "width_cm": 900,
            "height_cm": 700,
        },
        "line_width_cm": 1.9,
        "min_edge_margin_cm": 20.0,
        "radius_presets_cm": [10, 15, 20, 25, 30, 40, 50, 70, 90, 120, 160, 180, 220, 300],
        "start_goal_hint": {
            "x": round_float(sg_center.x),
            "y": round_float(sg_center.y),
            "length": 100.0,
        },
        "circles": helper_circles,
    }

    return course, helper_circles, reference_arcs, reference_tangents


def endpoint_after_block(pos: Vec2, theta: float, length_m: float, curvature: float) -> tuple[Vec2, float]:
    if abs(curvature) < 1e-12:
        return Vec2(pos.x + 100.0 * length_m * math.cos(theta), pos.y + 100.0 * length_m * math.sin(theta)), theta

    delta_theta = curvature * length_m
    radius_m = 1.0 / curvature
    end_x = pos.x + 100.0 * radius_m * (math.sin(theta + delta_theta) - math.sin(theta))
    end_y = pos.y + 100.0 * -radius_m * (math.cos(theta + delta_theta) - math.cos(theta))
    return Vec2(end_x, end_y), theta + delta_theta


def same_helper_circle(arc: ReferenceArc, center: Vec2, radius: float, turn: str) -> bool:
    return arc.turn == turn and abs(arc.radius - radius) < 0.1 and arc.center.distance_to(center) < 0.1


def point_dict(point: Vec2) -> dict[str, float]:
    return {"x": round_float(point.x), "y": round_float(point.y)}


def round_float(value: float) -> float:
    return round(value, 9)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
