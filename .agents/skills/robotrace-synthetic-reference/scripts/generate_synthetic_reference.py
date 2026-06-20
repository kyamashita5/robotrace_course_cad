#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "robotrace_course_cad").is_dir():
            return parent
    raise RuntimeError("Could not find robotrace_course_cad repository root")


ROOT = find_repo_root()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robotrace_course_cad.io.json_io import load_course_model  # noqa: E402
from robotrace_course_cad.solver.course_solver import solve_course  # noqa: E402


def number(value: float) -> float:
    rounded = round(float(value), 9)
    if rounded == -0.0:
        return 0.0
    return rounded


def point(vec) -> dict[str, float]:
    return {"x": number(vec.x), "y": number(vec.y)}


def helper_circle_payload(model) -> dict[str, list[dict[str, object]]]:
    return {
        "helper_circles": [
            {
                "id": circle.id,
                "x": number(circle.x),
                "y": number(circle.y),
                "r": number(circle.r),
                "turn": circle.turn.value,
            }
            for circle in model.circles
        ]
    }


def arc_payload(solution) -> dict[str, list[dict[str, object]]]:
    return {
        "arcs": [
            {
                "circle_id": arc.circle_id,
                "center": point(arc.center),
                "radius": number(arc.radius),
                "turn": arc.turn.value,
                "p_start": point(arc.p_start),
                "p_end": point(arc.p_end),
                "angle_rad": number(arc.angle_rad),
                "length_cm": number(arc.length),
            }
            for arc in solution.arcs
            if arc is not None
        ]
    }


def tangent_payload(solution) -> dict[str, list[dict[str, object]]]:
    return {
        "tangents": [
            {
                "from_circle_id": tangent.from_circle_id,
                "to_circle_id": tangent.to_circle_id,
                "p_from": point(tangent.p_from),
                "p_to": point(tangent.p_to),
                "length_cm": number(tangent.length),
            }
            for tangent in solution.tangents
            if tangent is not None
        ]
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate(course_name: str, source_dir: Path, examples_dir: Path, reference_dir: Path) -> tuple[int, int, int]:
    source_path = source_dir / f"{course_name}.json"
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    example_path = examples_dir / f"{course_name}.json"
    examples_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, example_path)

    model = load_course_model(example_path)
    solution = solve_course(model)
    errors = [issue.message for issue in solution.issues if issue.severity == "error"]
    if errors:
        raise RuntimeError(f"{course_name}: solver errors: {errors}")

    helpers = helper_circle_payload(model)
    arcs = arc_payload(solution)
    tangents = tangent_payload(solution)

    write_json(reference_dir / f"{course_name}_helper_circles.json", helpers)
    write_json(reference_dir / f"{course_name}_arcs.json", arcs)
    write_json(reference_dir / f"{course_name}_tangents.json", tangents)

    return len(helpers["helper_circles"]), len(arcs["arcs"]), len(tangents["tangents"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic examples and references for Robotrace Course CAD.")
    parser.add_argument("course_names", nargs="+", help="Course names without .json")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--examples-dir", type=Path, default=ROOT / "examples" / "synthetic")
    parser.add_argument("--reference-dir", type=Path, default=ROOT / "examples" / "synthetic_reference")
    args = parser.parse_args()

    for course_name in args.course_names:
        helper_count, arc_count, tangent_count = generate(
            course_name,
            args.source_dir,
            args.examples_dir,
            args.reference_dir,
        )
        print(f"{course_name}: helpers={helper_count} arcs={arc_count} tangents={tangent_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
