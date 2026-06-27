from __future__ import annotations

import math

from robotrace_course_cad.model.course_model import Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, MaterialEstimate

SHEET_R10_270 = "R10_270deg_arc"
SHEET_R10_90 = "R10_90deg_arc"
SHEET_R15_90 = "R15_90deg_arc"
SHEET_R20_90 = "R20_90deg_arc"
SHEET_R25_90 = "R25_90deg_arc"
SHEET_R30_90 = "R30_90deg_arc"
SHEET_R50_60_SLALOM = "R50_60cm_slalom"
SHEET_MARKER = "marker"

ARC_90_SHEET_BY_RADIUS = {
    10.0: SHEET_R10_90,
    15.0: SHEET_R15_90,
    20.0: SHEET_R20_90,
    25.0: SHEET_R25_90,
    30.0: SHEET_R30_90,
}

RADIUS_TOLERANCE_CM = 0.05
SLALOM_DISTANCE_TOLERANCE_CM = 0.2
SLALOM_ANGLE_TOLERANCE_DEG = 1.0
ANGLE_REMAINDER_EPSILON_DEG = 1e-6
SLALOM_SMALL_ANGLE_DEG = math.degrees(math.asin(0.3))
SLALOM_MIDDLE_ANGLE_DEG = SLALOM_SMALL_ANGLE_DEG * 2.0


def estimate_materials(solution: CourseSolution) -> MaterialEstimate:
    sheets: dict[str, int] = {}
    vinyl_tape_length_cm = sum(tangent.length for tangent in solution.tangents if tangent is not None)

    covered_arc_indexes = r50_slalom_arc_indexes(solution.arcs, sheets)
    for index, arc in enumerate(solution.arcs):
        if arc is None or index in covered_arc_indexes:
            continue
        if add_arc_cutting_sheets(arc, sheets):
            continue
        vinyl_tape_length_cm += arc.length

    marker_count = len(solution.corner_markers) + len(solution.start_goal_markers)
    if marker_count:
        sheets[SHEET_MARKER] = marker_count

    return MaterialEstimate(cutting_sheets=sheets, vinyl_tape_length_cm=vinyl_tape_length_cm)


def r50_slalom_arc_indexes(arcs: list[ArcSegment | None], sheets: dict[str, int]) -> set[int]:
    covered: set[int] = set()
    index = 0
    while index <= len(arcs) - 3:
        group = arcs[index : index + 3]
        if all(arc is not None for arc in group):
            first, second, third = group
            assert first is not None and second is not None and third is not None
            if is_r50_60_slalom_group(first, second, third):
                sheets[SHEET_R50_60_SLALOM] = sheets.get(SHEET_R50_60_SLALOM, 0) + 1
                covered.update({index, index + 1, index + 2})
                index += 3
                continue
        index += 1
    return covered


def is_r50_60_slalom_group(first: ArcSegment, second: ArcSegment, third: ArcSegment) -> bool:
    if not all(is_close(arc.radius, 50.0, RADIUS_TOLERANCE_CM) for arc in (first, second, third)):
        return False
    turns = (first.turn, second.turn, third.turn)
    if turns not in ((Turn.CW, Turn.CCW, Turn.CW), (Turn.CCW, Turn.CW, Turn.CCW)):
        return False
    if not is_close(first.center.distance_to(second.center), 100.0, SLALOM_DISTANCE_TOLERANCE_CM):
        return False
    if not is_close(second.center.distance_to(third.center), 100.0, SLALOM_DISTANCE_TOLERANCE_CM):
        return False
    if not is_close(first.center.distance_to(third.center), 60.0, SLALOM_DISTANCE_TOLERANCE_CM):
        return False

    angles = [arc_angle_deg(first), arc_angle_deg(second), arc_angle_deg(third)]
    expected = [SLALOM_SMALL_ANGLE_DEG, SLALOM_MIDDLE_ANGLE_DEG, SLALOM_SMALL_ANGLE_DEG]
    return all(is_close(angle, expected_angle, SLALOM_ANGLE_TOLERANCE_DEG) for angle, expected_angle in zip(angles, expected))


def add_arc_cutting_sheets(arc: ArcSegment, sheets: dict[str, int]) -> bool:
    radius = matched_sheet_radius(arc.radius)
    if radius is None:
        return False

    angle_deg = arc_angle_deg(arc)
    if angle_deg <= ANGLE_REMAINDER_EPSILON_DEG:
        return True

    if radius == 10.0:
        sheets_270 = int(angle_deg / 270.0)
        remainder = angle_deg - 270.0 * sheets_270
        if sheets_270:
            sheets[SHEET_R10_270] = sheets.get(SHEET_R10_270, 0) + sheets_270
        if remainder > ANGLE_REMAINDER_EPSILON_DEG:
            sheets[SHEET_R10_90] = sheets.get(SHEET_R10_90, 0) + math.ceil(remainder / 90.0)
        return True

    sheet_name = ARC_90_SHEET_BY_RADIUS[radius]
    sheets[sheet_name] = sheets.get(sheet_name, 0) + math.ceil(angle_deg / 90.0)
    return True


def matched_sheet_radius(radius: float) -> float | None:
    for available_radius in ARC_90_SHEET_BY_RADIUS:
        if is_close(radius, available_radius, RADIUS_TOLERANCE_CM):
            return available_radius
    return None


def arc_angle_deg(arc: ArcSegment) -> float:
    return math.degrees(arc.angle_rad)


def is_close(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= tolerance
