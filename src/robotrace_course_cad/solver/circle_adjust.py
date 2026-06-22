from __future__ import annotations

import math

from robotrace_course_cad.model.course_model import HelperCircle
from robotrace_course_cad.model.geometry import EPSILON, Vec2

TOUCH_DISTANCE_EPSILON_CM = 1e-6


def adjusted_center_touching_neighbors(circles: list[HelperCircle], index: int) -> Vec2 | None:
    if len(circles) < 3 or not 0 <= index < len(circles):
        return None

    previous = circles[(index - 1) % len(circles)]
    selected = circles[index]
    next_circle = circles[(index + 1) % len(circles)]

    distance_to_previous = helper_circle_touch_distance(previous, selected)
    distance_to_next = helper_circle_touch_distance(next_circle, selected)
    if distance_to_previous <= TOUCH_DISTANCE_EPSILON_CM or distance_to_next <= TOUCH_DISTANCE_EPSILON_CM:
        return None

    degenerate_center = projected_center_for_degenerate_neighbor_touch(
        selected.center,
        previous.center,
        distance_to_previous,
        next_circle.center,
        distance_to_next,
    )
    if degenerate_center is not None:
        return degenerate_center

    candidates = circle_intersection_points(
        previous.center,
        distance_to_previous,
        next_circle.center,
        distance_to_next,
    )
    if not candidates:
        return None

    return min(candidates, key=lambda point: point.distance_to(selected.center))


def adjusted_center_touching_previous(circles: list[HelperCircle], index: int) -> Vec2 | None:
    if len(circles) < 2 or not 0 <= index < len(circles):
        return None
    return adjusted_center_touching_anchor(circles[index], circles[(index - 1) % len(circles)])


def adjusted_center_touching_next(circles: list[HelperCircle], index: int) -> Vec2 | None:
    if len(circles) < 2 or not 0 <= index < len(circles):
        return None
    return adjusted_center_touching_anchor(circles[index], circles[(index + 1) % len(circles)])


def adjusted_center_touching_anchor(moving: HelperCircle, anchor: HelperCircle) -> Vec2 | None:
    direction_to_anchor = anchor.center - moving.center
    current_distance = direction_to_anchor.norm()
    target_distance = helper_circle_touch_distance(anchor, moving)

    if current_distance <= EPSILON or target_distance <= TOUCH_DISTANCE_EPSILON_CM:
        return None

    # c' = c + t(c_anchor - c), so |c' - c_anchor| = |1 - t| * current_distance.
    t_candidates = [
        1.0 - target_distance / current_distance,
        1.0 + target_distance / current_distance,
    ]
    best_t = min(t_candidates, key=lambda t: t * t)
    return moving.center + direction_to_anchor * best_t


def helper_circle_touch_distance(anchor: HelperCircle, moving: HelperCircle) -> float:
    if anchor.turn == moving.turn:
        return abs(anchor.r - moving.r)
    return anchor.r + moving.r


def projected_center_for_degenerate_neighbor_touch(
    current: Vec2,
    previous_center: Vec2,
    distance_to_previous: float,
    next_center: Vec2,
    distance_to_next: float,
) -> Vec2 | None:
    if previous_center.distance_to(next_center) > TOUCH_DISTANCE_EPSILON_CM:
        return None
    if abs(distance_to_previous - distance_to_next) > TOUCH_DISTANCE_EPSILON_CM:
        return None
    direction = current - previous_center
    current_distance = direction.norm()
    if current_distance <= EPSILON:
        return None
    return previous_center + direction * (distance_to_previous / current_distance)


def circle_intersection_points(c0: Vec2, r0: float, c1: Vec2, r1: float) -> list[Vec2]:
    delta = c1 - c0
    distance = delta.norm()

    if distance <= EPSILON:
        return []
    if distance > r0 + r1 + TOUCH_DISTANCE_EPSILON_CM:
        return []
    if distance < abs(r0 - r1) - TOUCH_DISTANCE_EPSILON_CM:
        return []

    a = (r0 * r0 - r1 * r1 + distance * distance) / (2.0 * distance)
    h2 = r0 * r0 - a * a
    if h2 < -TOUCH_DISTANCE_EPSILON_CM:
        return []

    base = c0 + delta * (a / distance)
    if abs(h2) <= TOUCH_DISTANCE_EPSILON_CM:
        return [base]

    h = math.sqrt(max(0.0, h2))
    offset = Vec2(-delta.y / distance * h, delta.x / distance * h)
    return [base + offset, base - offset]
