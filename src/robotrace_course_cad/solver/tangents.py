from __future__ import annotations

import math

from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.course_solution import TangentSegment
from robotrace_course_cad.model.geometry import EPSILON, Vec2, point_line_distance


def tangent_candidates_by_turn(c1: HelperCircle, c2: HelperCircle) -> list[TangentSegment]:
    kind = "outer" if c1.turn == c2.turn else "inner"
    r2_eff = c2.r if kind == "outer" else -c2.r
    return common_tangent_candidates(c1, c2, r2_eff, kind)


def oriented_tangent_candidates_by_turn(c1: HelperCircle, c2: HelperCircle) -> list[TangentSegment]:
    return [
        candidate
        for candidate in tangent_candidates_by_turn(c1, c2)
        if tangent_matches_course_direction(c1, c2, candidate)
    ]


def common_tangent_candidates(
    c1: HelperCircle,
    c2: HelperCircle,
    r2_eff: float,
    kind: str,
) -> list[TangentSegment]:
    delta = c2.center - c1.center
    d2 = delta.dot(delta)
    if d2 < EPSILON:
        return []

    dr = c1.r - r2_eff
    h2 = d2 - dr * dr
    if h2 < -1e-6:
        return []

    h = math.sqrt(max(0.0, h2))
    candidates: list[TangentSegment] = []

    for choice, sign in enumerate((-1.0, 1.0)):
        normal = Vec2(
            (delta.x * dr + -delta.y * h * sign) / d2,
            (delta.y * dr + delta.x * h * sign) / d2,
        )
        p_from = c1.center + normal * c1.r
        p_to = c2.center + normal * r2_eff
        candidates.append(
            TangentSegment(
                from_circle_id=c1.id,
                to_circle_id=c2.id,
                p_from=p_from,
                p_to=p_to,
                kind=kind,
                choice=choice,
            )
        )

    return candidates


def choose_tangent_closest_to_point(
    candidates: list[TangentSegment],
    point: Vec2,
) -> TangentSegment:
    return min(candidates, key=lambda t: point_line_distance(point, t.p_from, t.p_to))


def tangent_matches_course_direction(
    c1: HelperCircle,
    c2: HelperCircle,
    tangent: TangentSegment,
    tolerance: float = 1e-6,
) -> bool:
    from_dir = circle_path_direction(c1, tangent.p_from)
    to_dir = circle_path_direction(c2, tangent.p_to)
    chord = tangent.p_to - tangent.p_from

    if chord.norm() < 1e-6:
        return from_dir.dot(to_dir) > 1.0 - tolerance

    line_dir = chord.normalized()
    return from_dir.dot(line_dir) > 1.0 - tolerance and to_dir.dot(line_dir) > 1.0 - tolerance


def circle_path_direction(circle: HelperCircle, point: Vec2) -> Vec2:
    radius_vector = (point - circle.center).normalized()
    if circle.turn == Turn.CCW:
        return radius_vector.left_normal()
    return radius_vector.right_normal()
