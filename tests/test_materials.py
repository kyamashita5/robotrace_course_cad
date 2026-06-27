from __future__ import annotations

import math
import unittest

from robotrace_course_cad.model.course_model import Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CornerMarker, CourseSolution, StartGoalMarker, TangentSegment
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.materials import (
    SHEET_MARKER,
    SHEET_R10_90,
    SHEET_R10_270,
    SHEET_R15_90,
    SHEET_R20_90,
    SHEET_R25_90,
    SHEET_R30_90,
    SHEET_R50_60_SLALOM,
    estimate_materials,
)


class MaterialEstimationTest(unittest.TestCase):
    def test_r10_uses_270_degree_sheets_before_90_degree_sheets(self) -> None:
        solution = CourseSolution(
            tangents=[],
            arcs=[arc(10.0, 280.0)],
            issues=[],
        )

        estimate = estimate_materials(solution)

        self.assertEqual(estimate.cutting_sheets[SHEET_R10_270], 1)
        self.assertEqual(estimate.cutting_sheets[SHEET_R10_90], 1)
        self.assertAlmostEqual(estimate.vinyl_tape_length_cm, 0.0)

    def test_90_degree_sheet_radii_round_arc_angle_up(self) -> None:
        solution = CourseSolution(
            tangents=[],
            arcs=[
                arc(15.0, 91.0),
                arc(15.0, 180.0),
                arc(20.0, 1.0),
                arc(25.0, 270.0),
                arc(30.0, 271.0),
            ],
            issues=[],
        )

        estimate = estimate_materials(solution)

        self.assertEqual(estimate.cutting_sheets[SHEET_R15_90], 4)
        self.assertEqual(estimate.cutting_sheets[SHEET_R20_90], 1)
        self.assertEqual(estimate.cutting_sheets[SHEET_R25_90], 3)
        self.assertEqual(estimate.cutting_sheets[SHEET_R30_90], 4)
        self.assertAlmostEqual(estimate.vinyl_tape_length_cm, 0.0)

    def test_unsupported_arcs_and_tangents_use_vinyl_tape(self) -> None:
        unsupported_arc = arc(40.0, 90.0)
        tangent = line(Vec2(0.0, 0.0), Vec2(100.0, 0.0))
        solution = CourseSolution(tangents=[tangent], arcs=[unsupported_arc], issues=[])

        estimate = estimate_materials(solution)

        self.assertEqual(estimate.cutting_sheets, {})
        self.assertAlmostEqual(estimate.vinyl_tape_length_cm, 100.0 + unsupported_arc.length)

    def test_markers_share_one_sheet_type(self) -> None:
        solution = CourseSolution(
            tangents=[],
            arcs=[],
            issues=[],
            corner_markers=[corner_marker(), corner_marker()],
            start_goal_markers=[start_goal_marker()],
        )

        estimate = estimate_materials(solution)

        self.assertEqual(estimate.cutting_sheets[SHEET_MARKER], 3)

    def test_r50_60cm_slalom_counts_one_slalom_sheet(self) -> None:
        solution = CourseSolution(tangents=[], arcs=r50_slalom_arcs(), issues=[])

        estimate = estimate_materials(solution)

        self.assertEqual(estimate.cutting_sheets[SHEET_R50_60_SLALOM], 1)
        self.assertAlmostEqual(estimate.vinyl_tape_length_cm, 0.0)


def arc(radius: float, angle_deg: float, turn: Turn = Turn.CCW, center: Vec2 = Vec2(0.0, 0.0)) -> ArcSegment:
    angle_rad = math.radians(angle_deg)
    direction = 1.0 if turn == Turn.CCW else -1.0
    p_end = Vec2(
        center.x + radius * math.cos(direction * angle_rad),
        center.y + radius * math.sin(direction * angle_rad),
    )
    return ArcSegment(
        circle_id=0,
        center=center,
        radius=radius,
        p_start=Vec2(center.x + radius, center.y),
        p_end=p_end,
        turn=turn,
        angle_rad=angle_rad,
        length=radius * angle_rad,
    )


def r50_slalom_arcs() -> list[ArcSegment]:
    radius = 50.0
    span = 60.0
    lateral = math.sqrt((2.0 * radius) ** 2 - (span / 2.0) ** 2)
    centers = [
        Vec2(0.0, -radius),
        Vec2(span / 2.0, lateral - radius),
        Vec2(span, -radius),
    ]
    p12 = midpoint(centers[0], centers[1])
    p23 = midpoint(centers[1], centers[2])
    return [
        slalom_arc(0, centers[0], Vec2(0.0, 0.0), p12, Turn.CW),
        slalom_arc(1, centers[1], p12, p23, Turn.CCW),
        slalom_arc(2, centers[2], p23, Vec2(span, 0.0), Turn.CW),
    ]


def slalom_arc(circle_id: int, center: Vec2, p_start: Vec2, p_end: Vec2, turn: Turn) -> ArcSegment:
    angle_rad = slalom_angle(center, p_start, p_end, turn)
    return ArcSegment(
        circle_id=circle_id,
        center=center,
        radius=50.0,
        p_start=p_start,
        p_end=p_end,
        turn=turn,
        angle_rad=angle_rad,
        length=50.0 * angle_rad,
    )


def slalom_angle(center: Vec2, p_start: Vec2, p_end: Vec2, turn: Turn) -> float:
    start = math.atan2(p_start.y - center.y, p_start.x - center.x)
    end = math.atan2(p_end.y - center.y, p_end.x - center.x)
    if turn == Turn.CCW:
        return (end - start) % (2.0 * math.pi)
    return (start - end) % (2.0 * math.pi)


def midpoint(first: Vec2, second: Vec2) -> Vec2:
    return (first + second) * 0.5


def line(start: Vec2, end: Vec2) -> TangentSegment:
    return TangentSegment(
        from_circle_id=0,
        to_circle_id=1,
        p_from=start,
        p_to=end,
        kind="outer",
        choice=0,
    )


def corner_marker() -> CornerMarker:
    return CornerMarker(
        boundary_index=0,
        point=Vec2(0.0, 0.0),
        center=Vec2(0.0, 7.0),
        tangent_angle_deg=0.0,
        normal_angle_deg=90.0,
    )


def start_goal_marker() -> StartGoalMarker:
    return StartGoalMarker(
        marker_index=0,
        point=Vec2(0.0, 0.0),
        center=Vec2(0.0, -7.0),
        tangent_angle_deg=0.0,
        normal_angle_deg=-90.0,
    )


if __name__ == "__main__":
    unittest.main()
