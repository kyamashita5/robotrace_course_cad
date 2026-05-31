from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.model.course_model import Turn
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.course_solver import solve_course
from robotrace_course_cad.solver.tangents import tangent_candidates_by_turn
from robotrace_course_cad.model.course_model import HelperCircle

try:
    from robotrace_course_cad.render.qt_renderer import _course_bounds_cm, _qt_arc_angles, to_scene
except ImportError:
    _course_bounds_cm = None
    _qt_arc_angles = None
    to_scene = None


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_EXAMPLES = ROOT / "examples" / "synthetic"
SYNTHETIC_REFERENCE = ROOT / "examples" / "synthetic_reference"
POINT_TOLERANCE_CM = 0.12


class SyntheticReferenceTest(unittest.TestCase):
    def test_common_tangent_candidates_include_reverse_orientation(self) -> None:
        c0 = HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW)
        c1 = HelperCircle(1, 50.0, 0.0, 10.0, Turn.CCW)

        candidates = tangent_candidates_by_turn(c0, c1)

        self.assertEqual(len(candidates), 2)
        self.assertTrue(any(abs(t.p_from.y + 10.0) < 1e-9 for t in candidates))
        self.assertTrue(any(abs(t.p_from.y - 10.0) < 1e-9 for t in candidates))

    def test_solver_matches_all_synthetic_reference_files(self) -> None:
        example_paths = sorted(SYNTHETIC_EXAMPLES.glob("*.json"))
        self.assertGreaterEqual(len(example_paths), 6)

        for example_path in example_paths:
            with self.subTest(course=example_path.stem):
                model = load_course_model(example_path)
                expected_arcs = load_reference(example_path.stem, "arcs")["arcs"]
                expected_tangents = load_reference(example_path.stem, "tangents")["tangents"]

                solution = solve_course(model)

                errors = [issue.message for issue in solution.issues if issue.severity == "error"]
                self.assertFalse(errors)
                self.assertEqual(len(solution.tangents), len(expected_tangents))
                self.assertEqual(len(solution.arcs), len(expected_arcs))

                for index, expected in enumerate(expected_arcs):
                    arc = solution.arcs[index]
                    self.assertIsNotNone(arc, f"arc {index} was not generated")
                    assert arc is not None
                    self.assertLess(point_distance(arc.p_start, expected["p_start"]), POINT_TOLERANCE_CM, f"arc {index} start")
                    self.assertLess(point_distance(arc.p_end, expected["p_end"]), POINT_TOLERANCE_CM, f"arc {index} end")
                    self.assertLess(abs(arc.length - expected["length_cm"]), POINT_TOLERANCE_CM, f"arc {index} length")

                for index, expected in enumerate(expected_tangents):
                    tangent = solution.tangents[index]
                    self.assertIsNotNone(tangent, f"tangent {index} was not generated")
                    assert tangent is not None
                    self.assertLess(point_distance(tangent.p_from, expected["p_from"]), POINT_TOLERANCE_CM, f"tangent {index} start")
                    self.assertLess(point_distance(tangent.p_to, expected["p_to"]), POINT_TOLERANCE_CM, f"tangent {index} end")
                    self.assertLess(abs(tangent.length - expected["length_cm"]), POINT_TOLERANCE_CM, f"tangent {index} length")

    @unittest.skipIf(_qt_arc_angles is None or to_scene is None, "PySide6 is not available")
    def test_qt_arc_angles_start_and_end_at_tangent_points(self) -> None:
        assert _qt_arc_angles is not None
        assert to_scene is not None

        for example_path in sorted(SYNTHETIC_EXAMPLES.glob("*.json")):
            with self.subTest(course=example_path.stem):
                model = load_course_model(example_path)
                solution = solve_course(model)

                for index, arc in enumerate(solution.arcs):
                    self.assertIsNotNone(arc, f"arc {index} was not generated")
                    assert arc is not None
                    start_angle, sweep_angle = _qt_arc_angles(arc)
                    start = point_on_qt_arc(arc.center, arc.radius, start_angle)
                    end = point_on_qt_arc(arc.center, arc.radius, start_angle + sweep_angle)
                    expected_start = to_scene(arc.p_start)
                    expected_end = to_scene(arc.p_end)

                    self.assertLess(scene_distance(start, expected_start), 1e-5, f"arc {index} Qt start")
                    self.assertLess(scene_distance(end, expected_end), 1e-5, f"arc {index} Qt end")

    @unittest.skipIf(_course_bounds_cm is None, "PySide6 is not available")
    def test_scene_bounds_cover_all_synthetic_courses(self) -> None:
        assert _course_bounds_cm is not None

        for example_path in sorted(SYNTHETIC_EXAMPLES.glob("*.json")):
            with self.subTest(course=example_path.stem):
                model = load_course_model(example_path)
                solution = solve_course(model)
                min_x, max_x, min_y, max_y = _course_bounds_cm(model, solution, margin_cm=0.0)

                for circle in model.circles:
                    self.assertLessEqual(min_x, circle.x - circle.r)
                    self.assertGreaterEqual(max_x, circle.x + circle.r)
                    self.assertLessEqual(min_y, circle.y - circle.r)
                    self.assertGreaterEqual(max_y, circle.y + circle.r)


def load_reference(course_name: str, kind: str):
    path = SYNTHETIC_REFERENCE / f"{course_name}_{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def point_distance(actual: Vec2, expected: dict[str, float]) -> float:
    return actual.distance_to(Vec2(expected["x"], expected["y"]))


def point_on_qt_arc(center: Vec2, radius: float, angle_deg: float):
    assert to_scene is not None
    angle_rad = math.radians(angle_deg)
    scene_center = to_scene(center)
    scene_radius = radius * 10.0
    return Vec2(
        scene_center.x() + scene_radius * math.cos(angle_rad),
        scene_center.y() - scene_radius * math.sin(angle_rad),
    )


def scene_distance(a: Vec2, b) -> float:
    return math.hypot(a.x - b.x(), a.y - b.y())


if __name__ == "__main__":
    unittest.main()
