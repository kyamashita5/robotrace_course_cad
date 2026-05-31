from __future__ import annotations

import math

from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, TangentSegment, ValidationIssue
from robotrace_course_cad.model.geometry import TAU, angle_ccw, angle_cw, point_angle

MIN_SEGMENT_LENGTH_CM = 10.0
FULL_CIRCLE_EPSILON_RAD = math.radians(3.0)


def arc_angle_for_turn(circle: HelperCircle, p_start, p_end) -> float:
    a0 = point_angle(circle.center, p_start)
    a1 = point_angle(circle.center, p_end)
    if circle.turn == Turn.CCW:
        return angle_ccw(a0, a1)
    return angle_cw(a0, a1)


def generate_arcs(
    circles: list[HelperCircle],
    tangents: list[TangentSegment | None],
) -> tuple[list[ArcSegment | None], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    n = len(circles)
    arcs: list[ArcSegment | None] = [None] * n

    for i, circle in enumerate(circles):
        prev_index = (i - 1) % n
        prev_tangent = tangents[prev_index] if prev_index < len(tangents) else None
        next_tangent = tangents[i] if i < len(tangents) else None

        if prev_tangent is None or next_tangent is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Circle {circle.id} is missing a neighboring tangent",
                    related_circle_ids=[circle.id],
                    related_connection_ids=[prev_index, i],
                )
            )
            continue

        angle_rad = arc_angle_for_turn(circle, prev_tangent.p_to, next_tangent.p_from)
        length = circle.r * angle_rad
        arcs[i] = ArcSegment(
            circle_id=circle.id,
            center=circle.center,
            radius=circle.r,
            p_start=prev_tangent.p_to,
            p_end=next_tangent.p_from,
            turn=circle.turn,
            angle_rad=angle_rad,
            length=length,
        )

        if length <= MIN_SEGMENT_LENGTH_CM:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=f"Arc on circle {circle.id} is short ({length:.1f} cm)",
                    related_circle_ids=[circle.id],
                    related_connection_ids=[prev_index, i],
                )
            )
        if angle_rad >= TAU - FULL_CIRCLE_EPSILON_RAD:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=f"Arc on circle {circle.id} is almost a full circle",
                    related_circle_ids=[circle.id],
                    related_connection_ids=[prev_index, i],
                )
            )

    return arcs, issues
