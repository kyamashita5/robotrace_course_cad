from __future__ import annotations

import math

from robotrace_course_cad.model.course_model import CourseModel, Turn
from robotrace_course_cad.model.course_solution import (
    ArcSegment,
    CornerMarker,
    CourseSolution,
    StartGoalMarker,
    StartGoalSegment,
    TangentSegment,
)
from robotrace_course_cad.model.geometry import EPSILON, Vec2, project_point_to_line

MARKER_OFFSET_CM = 7.0
ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM = 1e-3


class _PathSegment:
    def __init__(self, kind: str, index: int, tangent: TangentSegment | None = None, arc: ArcSegment | None = None):
        self.kind = kind
        self.index = index
        self.tangent = tangent
        self.arc = arc

    @property
    def p_start(self) -> Vec2:
        if self.tangent is not None:
            return self.tangent.p_from
        assert self.arc is not None
        return self.arc.p_start

    @property
    def p_end(self) -> Vec2:
        if self.tangent is not None:
            return self.tangent.p_to
        assert self.arc is not None
        return self.arc.p_end

    @property
    def length(self) -> float:
        if self.tangent is not None:
            return self.tangent.length
        assert self.arc is not None
        return self.arc.length

    def direction_at_start(self) -> Vec2 | None:
        if self.tangent is not None:
            return line_direction(self.tangent)
        assert self.arc is not None
        return arc_direction_at(self.arc, self.arc.p_start)

    def direction_at_end(self) -> Vec2 | None:
        if self.tangent is not None:
            return line_direction(self.tangent)
        assert self.arc is not None
        return arc_direction_at(self.arc, self.arc.p_end)


def generate_corner_markers(solution: CourseSolution) -> list[CornerMarker]:
    segments = marker_path_segments(solution)
    markers: list[CornerMarker] = []

    if len(segments) < 2:
        return markers

    for index, previous in enumerate(segments):
        next_segment = segments[(index + 1) % len(segments)]
        point = midpoint(previous.p_end, next_segment.p_start)
        if any(marker.point.distance_to(point) < 0.05 for marker in markers):
            continue

        direction = boundary_direction(previous, next_segment)
        if direction is None:
            continue

        left = direction.left_normal().normalized()
        center = point + left * MARKER_OFFSET_CM
        tangent_angle = math.degrees(math.atan2(direction.y, direction.x))
        normal_angle = math.degrees(math.atan2(left.y, left.x))
        markers.append(
            CornerMarker(
                boundary_index=len(markers),
                point=point,
                center=center,
                tangent_angle_deg=tangent_angle,
                normal_angle_deg=normal_angle,
            )
        )

    return markers


def generate_start_goal_segment_and_markers(
    model: CourseModel,
    tangents: list[TangentSegment | None],
) -> tuple[StartGoalSegment | None, list[StartGoalMarker]]:
    if not tangents:
        return None, []

    sg_tangent = tangents[-1]
    if sg_tangent is None or sg_tangent.length <= ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM:
        return None, []

    direction = line_direction(sg_tangent)
    if direction is None:
        return None, []

    sg_center = project_point_to_line(model.start_goal_hint.center, sg_tangent.p_from, sg_tangent.p_to)
    half_length = model.start_goal_hint.length / 2.0
    p_start = sg_center - direction * half_length
    p_end = sg_center + direction * half_length
    tangent_angle = math.degrees(math.atan2(direction.y, direction.x))

    segment = StartGoalSegment(
        center=sg_center,
        p_start=p_start,
        p_end=p_end,
        tangent_angle_deg=tangent_angle,
        length=model.start_goal_hint.length,
    )

    right = direction.right_normal().normalized()
    normal_angle = math.degrees(math.atan2(right.y, right.x))
    markers = [
        StartGoalMarker(
            marker_index=0,
            point=p_start,
            center=p_start + right * MARKER_OFFSET_CM,
            tangent_angle_deg=tangent_angle,
            normal_angle_deg=normal_angle,
        ),
        StartGoalMarker(
            marker_index=1,
            point=p_end,
            center=p_end + right * MARKER_OFFSET_CM,
            tangent_angle_deg=tangent_angle,
            normal_angle_deg=normal_angle,
        ),
    ]
    return segment, markers


def marker_path_segments(solution: CourseSolution) -> list[_PathSegment]:
    n = max(len(solution.arcs), len(solution.tangents))
    segments: list[_PathSegment] = []

    for i in range(n):
        if i < len(solution.arcs) and solution.arcs[i] is not None:
            segment = _PathSegment("arc", i, arc=solution.arcs[i])
            if segment.length > ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM:
                segments.append(segment)
        if i < len(solution.tangents) and solution.tangents[i] is not None:
            segment = _PathSegment("line", i, tangent=solution.tangents[i])
            if segment.length > ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM:
                segments.append(segment)

    return segments


def boundary_direction(previous: _PathSegment, next_segment: _PathSegment) -> Vec2 | None:
    previous_direction = previous.direction_at_end() if previous.length > ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM else None
    next_direction = next_segment.direction_at_start() if next_segment.length > ZERO_LENGTH_MARKER_SEGMENT_EPSILON_CM else None

    if previous_direction is not None and next_direction is not None:
        if previous_direction.dot(next_direction) > 0.0:
            return (previous_direction + next_direction).normalized()
        return next_direction
    return next_direction or previous_direction


def line_direction(tangent: TangentSegment) -> Vec2 | None:
    delta = tangent.p_to - tangent.p_from
    if delta.norm() < EPSILON:
        return None
    return delta.normalized()


def arc_direction_at(arc: ArcSegment, point: Vec2) -> Vec2:
    radius = (point - arc.center).normalized()
    if arc.turn == Turn.CCW:
        return radius.left_normal()
    return radius.right_normal()


def midpoint(a: Vec2, b: Vec2) -> Vec2:
    return (a + b) * 0.5
