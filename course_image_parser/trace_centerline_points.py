#!/usr/bin/env python3
"""Extract a centerline skeleton from a normalized course image and trace it as a point sequence."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from detect_start_goal_area import BOARD_OUT_DIR, OUT_DIR as START_GOAL_OUT_DIR, normalize_board_image, to_board_cm


OUT_DIR = Path("tmp/centerline_trace")


@dataclass(frozen=True)
class TracePoint:
    index: int
    x_px: float
    y_px: float
    x_cm: float
    y_cm: float
    heading_deg: float


@dataclass(frozen=True)
class TraceResult:
    points: list[TracePoint]
    reached_goal: bool
    goal_distance_px: float
    travel_cm: float
    snapped_start_px: tuple[float, float]
    snapped_goal_px: tuple[float, float]


def parse_point_cm(raw_value: str) -> tuple[float, float]:
    values = [token.strip() for token in raw_value.split(",")]
    if len(values) != 2:
        raise ValueError(f"invalid point format: {raw_value}")
    return float(values[0]), float(values[1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--name")
    parser.add_argument("--json-path")
    parser.add_argument("--width-cm", type=float)
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--board-out-dir", default=str(BOARD_OUT_DIR))
    parser.add_argument("--start-goal-out-dir", default=str(START_GOAL_OUT_DIR))
    parser.add_argument("--px-per-cm", type=int, default=4)
    parser.add_argument("--board-color", default="cyan")
    parser.add_argument("--candidate-cell-sizes", default="135x90,180x90,90x135,90x180")
    parser.add_argument("--black-threshold", type=int, default=120)
    parser.add_argument("--normalized-input", action="store_true")
    parser.add_argument("--start-cm", required=True, help="confirmed START point as x,y in board cm")
    parser.add_argument("--goal-cm", required=True, help="confirmed GOAL point as x,y in board cm")
    parser.add_argument("--line-threshold", type=int, default=150)
    parser.add_argument("--erode-size", type=int, default=5)
    parser.add_argument("--dilate-size", type=int, default=5)
    parser.add_argument("--open-erode-size", type=int, default=5)
    parser.add_argument("--open-dilate-size", type=int, default=5)
    parser.add_argument("--close-dilate-size", type=int, default=5)
    parser.add_argument("--close-erode-size", type=int, default=5)
    parser.add_argument("--step-cm", type=float, default=1.0)
    parser.add_argument("--max-step-cm", type=float, default=5.0)
    parser.add_argument("--step-tolerance-cm", type=float, default=0.75)
    parser.add_argument("--angle-tolerance-deg", type=float, default=30.0)
    parser.add_argument("--goal-tolerance-cm", type=float, default=2.5)
    parser.add_argument("--min-goal-travel-cm", type=float, default=150.0)
    parser.add_argument("--max-points", type=int, default=4000)
    parser.add_argument("--recent-exclusion-points", type=int, default=8)
    return parser.parse_args()


def cm_to_image_px(point_cm: tuple[float, float], board_height_cm: float, px_per_cm: int) -> np.ndarray:
    x_cm, y_cm = point_cm
    return np.array([x_cm * px_per_cm, (board_height_cm - y_cm) * px_per_cm], dtype=np.float32)


def heading_to_degrees(heading: np.ndarray) -> float:
    return math.degrees(math.atan2(float(heading[1]), float(heading[0])))


def heading_degrees_between(p0_cm: tuple[float, float], p1_cm: tuple[float, float], fallback_deg: float) -> float:
    dx = p1_cm[0] - p0_cm[0]
    dy = p1_cm[1] - p0_cm[1]
    if math.hypot(dx, dy) <= 1e-9:
        return fallback_deg
    return math.degrees(math.atan2(dy, dx))


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-6:
        raise ValueError("zero-length direction vector")
    return vector / norm


def extract_black_mask(image: np.ndarray, threshold: int) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    cyan_like = (hue >= 80) & (hue <= 110) & (saturation >= 30)
    magenta_like = (hue >= 135) & (hue <= 175) & (saturation >= 30)
    yellow_like = (hue >= 15) & (hue <= 45) & (saturation >= 30)
    colored_overlay = cyan_like | magenta_like | yellow_like

    # Keep only genuinely dark, low-saturation pixels so board/grid annotations
    # do not leak into the centerline mask through interpolation artifacts.
    dark_black = value <= threshold
    deep_black = value <= min(threshold, 110)
    low_saturation = saturation <= 70
    mid_gray = (saturation <= 40) & (value >= 125)

    black_mask = ((dark_black & low_saturation) | deep_black) & ~colored_overlay & ~mid_gray
    return (black_mask.astype(np.uint8) * 255)


def clean_mask(
    mask: np.ndarray,
    open_erode_size: int,
    open_dilate_size: int,
    close_dilate_size: int,
    close_erode_size: int,
) -> np.ndarray:
    open_erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_erode_size, open_erode_size))
    open_dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_dilate_size, open_dilate_size))
    close_dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_dilate_size, close_dilate_size))
    close_erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_erode_size, close_erode_size))

    eroded_once = cv2.erode(mask, open_erode_kernel, iterations=1)
    dilated_once = cv2.dilate(eroded_once, open_dilate_kernel, iterations=1)
    dilated_twice = cv2.dilate(dilated_once, close_dilate_kernel, iterations=1)
    eroded_twice = cv2.erode(dilated_twice, close_erode_kernel, iterations=1)
    return eroded_twice


def zhang_suen_thinning(mask: np.ndarray) -> np.ndarray:
    skeleton = (mask > 0).astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            padded = np.pad(skeleton, 1, mode="constant")
            p2 = padded[:-2, 1:-1]
            p3 = padded[:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, :-2]
            p8 = padded[1:-1, :-2]
            p9 = padded[:-2, :-2]

            neighbors = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            transitions = (
                ((p2 == 0) & (p3 == 1)).astype(np.uint8)
                + ((p3 == 0) & (p4 == 1)).astype(np.uint8)
                + ((p4 == 0) & (p5 == 1)).astype(np.uint8)
                + ((p5 == 0) & (p6 == 1)).astype(np.uint8)
                + ((p6 == 0) & (p7 == 1)).astype(np.uint8)
                + ((p7 == 0) & (p8 == 1)).astype(np.uint8)
                + ((p8 == 0) & (p9 == 1)).astype(np.uint8)
                + ((p9 == 0) & (p2 == 1)).astype(np.uint8)
            )

            common = (skeleton == 1) & (neighbors >= 2) & (neighbors <= 6) & (transitions == 1)
            if step == 0:
                removable = common & ((p2 * p4 * p6) == 0) & ((p4 * p6 * p8) == 0)
            else:
                removable = common & ((p2 * p4 * p8) == 0) & ((p2 * p6 * p8) == 0)

            if np.any(removable):
                skeleton[removable] = 0
                changed = True
    return skeleton.astype(np.uint8) * 255


def snap_to_mask_point(target: np.ndarray, mask: np.ndarray, max_radius_px: float) -> np.ndarray:
    coords = np.argwhere(mask > 0)
    if coords.size == 0:
        raise ValueError("mask has no non-zero pixels")
    xy_coords = coords[:, ::-1].astype(np.float32)
    deltas = xy_coords - target[None, :]
    distances = np.linalg.norm(deltas, axis=1)
    best_index = int(np.argmin(distances))
    best_distance = float(distances[best_index])
    if best_distance > max_radius_px:
        raise ValueError(f"no skeleton pixel found within {max_radius_px:.1f}px of target point")
    return xy_coords[best_index]


def weighted_heading(points_xy: list[np.ndarray], previous_heading: np.ndarray) -> np.ndarray:
    weights = np.arange(1, len(points_xy) + 1, dtype=np.float32)
    matrix = np.stack(points_xy, axis=0).astype(np.float32)
    centroid = np.average(matrix, axis=0, weights=weights)
    centered = matrix - centroid
    weighted = centered * weights[:, None]
    covariance = weighted.T @ centered
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    direction = eigenvectors[:, int(np.argmax(eigenvalues))].astype(np.float32)

    span = matrix[-1] - matrix[0]
    if float(np.linalg.norm(span)) > 1e-6 and float(np.dot(direction, span)) < 0.0:
        direction = -direction
    elif float(np.dot(direction, previous_heading)) < 0.0:
        direction = -direction
    return normalize_vector(direction)


def build_fit_history(trace_points_xy: list[np.ndarray], seed_history_xy: list[np.ndarray], history_count: int = 5) -> list[np.ndarray]:
    if len(trace_points_xy) >= history_count:
        return trace_points_xy[-history_count:]
    missing = history_count - len(trace_points_xy)
    return seed_history_xy[-missing:] + trace_points_xy


def choose_next_point(
    current_xy: np.ndarray,
    heading_xy: np.ndarray,
    skeleton_coords_xy: np.ndarray,
    accepted_points_xy: list[np.ndarray],
    step_px: float,
    max_step_px: float,
    px_per_cm: int,
    step_tolerance_px: float,
    angle_tolerance_deg: float,
    recent_exclusion_points: int,
    goal_xy: np.ndarray,
    goal_tolerance_px: float,
    reached_goal_window: bool,
) -> np.ndarray | None:
    deltas = skeleton_coords_xy - current_xy[None, :]
    distances = np.linalg.norm(deltas, axis=1)
    min_step_cm = max(1, int(round(step_px / float(px_per_cm))))
    max_step_cm = max(min_step_cm, int(round(max_step_px / float(px_per_cm))))

    for search_step_cm in range(min_step_cm, max_step_cm + 1):
        search_step_px = float(search_step_cm * px_per_cm)
        distance_mask = np.abs(distances - search_step_px) <= step_tolerance_px
        if not np.any(distance_mask):
            continue

        candidate_deltas = deltas[distance_mask]
        candidate_points = skeleton_coords_xy[distance_mask]
        candidate_distances = distances[distance_mask]
        unit_deltas = candidate_deltas / np.maximum(candidate_distances[:, None], 1e-6)
        cosines = np.clip(unit_deltas @ heading_xy, -1.0, 1.0)
        angle_diffs = np.degrees(np.arccos(cosines))
        angle_mask = angle_diffs <= angle_tolerance_deg
        if not np.any(angle_mask):
            continue

        candidate_points = candidate_points[angle_mask]
        candidate_distances = candidate_distances[angle_mask]
        angle_diffs = angle_diffs[angle_mask]

        if accepted_points_xy:
            recent_points = accepted_points_xy[-recent_exclusion_points:]
            keep_mask = np.ones(candidate_points.shape[0], dtype=bool)
            for index, candidate in enumerate(candidate_points):
                if reached_goal_window and float(np.linalg.norm(candidate - goal_xy)) <= goal_tolerance_px:
                    continue
                if any(float(np.linalg.norm(candidate - prior)) < search_step_px * 0.55 for prior in recent_points):
                    keep_mask[index] = False
            candidate_points = candidate_points[keep_mask]
            candidate_distances = candidate_distances[keep_mask]
            angle_diffs = angle_diffs[keep_mask]
            if candidate_points.size == 0:
                continue

        scores = angle_diffs + np.abs(candidate_distances - search_step_px) * 2.0
        best_index = int(np.argmin(scores))
        return candidate_points[best_index]

    return None


def trace_centerline(
    skeleton_mask: np.ndarray,
    start_xy: np.ndarray,
    goal_xy: np.ndarray,
    board_height_cm: float,
    px_per_cm: int,
    step_cm: float,
    max_step_cm: float,
    step_tolerance_cm: float,
    angle_tolerance_deg: float,
    goal_tolerance_cm: float,
    min_goal_travel_cm: float,
    max_points: int,
    recent_exclusion_points: int,
) -> TraceResult:
    skeleton_coords_xy = np.argwhere(skeleton_mask > 0)[:, ::-1].astype(np.float32)
    if skeleton_coords_xy.size == 0:
        raise ValueError("skeleton mask is empty")

    step_px = step_cm * px_per_cm
    max_step_px = max_step_cm * px_per_cm
    step_tolerance_px = step_tolerance_cm * px_per_cm
    goal_tolerance_px = goal_tolerance_cm * px_per_cm
    snap_radius_px = max(step_px * 2.0, goal_tolerance_px * 2.0)

    snapped_start_xy = snap_to_mask_point(start_xy, skeleton_mask, snap_radius_px)
    snapped_goal_xy = snap_to_mask_point(goal_xy, skeleton_mask, snap_radius_px)

    initial_heading = normalize_vector(snapped_start_xy - snapped_goal_xy)
    seed_history_xy = [snapped_start_xy - initial_heading * step_px * scale for scale in (4, 3, 2, 1)]
    accepted_points_xy: list[np.ndarray] = [snapped_start_xy]
    headings_xy: list[np.ndarray] = [initial_heading]

    reached_goal = False
    for _ in range(max_points - 1):
        current_xy = accepted_points_xy[-1]
        current_heading = headings_xy[-1]
        travel_cm = max(0.0, (len(accepted_points_xy) - 1) * step_cm)
        next_xy = choose_next_point(
            current_xy=current_xy,
            heading_xy=current_heading,
            skeleton_coords_xy=skeleton_coords_xy,
            accepted_points_xy=accepted_points_xy,
            step_px=step_px,
            max_step_px=max_step_px,
            px_per_cm=px_per_cm,
            step_tolerance_px=step_tolerance_px,
            angle_tolerance_deg=angle_tolerance_deg,
            recent_exclusion_points=recent_exclusion_points,
            goal_xy=snapped_goal_xy,
            goal_tolerance_px=goal_tolerance_px,
            reached_goal_window=travel_cm >= min_goal_travel_cm,
        )
        if next_xy is None:
            break

        accepted_points_xy.append(next_xy)
        fit_history = build_fit_history(accepted_points_xy, seed_history_xy, history_count=5)
        headings_xy.append(weighted_heading(fit_history, current_heading))

        if travel_cm >= min_goal_travel_cm and float(np.linalg.norm(next_xy - snapped_goal_xy)) <= goal_tolerance_px:
            reached_goal = True
            break

    trace_points: list[TracePoint] = []
    for index, (point_xy, heading_xy) in enumerate(zip(accepted_points_xy, headings_xy)):
        x_cm, y_cm = to_board_cm((float(point_xy[0]), float(point_xy[1])), board_height_cm, px_per_cm)
        trace_points.append(
            TracePoint(
                index=index,
                x_px=float(point_xy[0]),
                y_px=float(point_xy[1]),
                x_cm=round(x_cm, 4),
                y_cm=round(y_cm, 4),
                heading_deg=round(heading_to_degrees(heading_xy), 4),
            )
        )

    goal_distance_px = float(np.linalg.norm(accepted_points_xy[-1] - snapped_goal_xy))
    travel_px = 0.0
    for previous_xy, current_xy in zip(accepted_points_xy[:-1], accepted_points_xy[1:]):
        travel_px += float(np.linalg.norm(current_xy - previous_xy))
    travel_cm = travel_px / float(px_per_cm)
    return TraceResult(
        points=trace_points,
        reached_goal=reached_goal,
        goal_distance_px=goal_distance_px,
        travel_cm=travel_cm,
        snapped_start_px=(float(snapped_start_xy[0]), float(snapped_start_xy[1])),
        snapped_goal_px=(float(snapped_goal_xy[0]), float(snapped_goal_xy[1])),
    )


def render_overlay(
    normalized_image: np.ndarray,
    trace: TraceResult,
    start_xy: np.ndarray,
    goal_xy: np.ndarray,
) -> np.ndarray:
    overlay = normalized_image.copy()
    polyline = np.array([[point.x_px, point.y_px] for point in trace.points], dtype=np.float32)
    if polyline.shape[0] >= 2:
        cv2.polylines(overlay, [np.round(polyline).astype(np.int32)], isClosed=False, color=(0, 0, 255), thickness=2, lineType=cv2.LINE_AA)
    for point in trace.points[:: max(1, len(trace.points) // 40 or 1)]:
        cv2.circle(overlay, (int(round(point.x_px)), int(round(point.y_px))), 3, (0, 128, 255), -1, cv2.LINE_AA)
    cv2.circle(overlay, tuple(np.round(start_xy).astype(np.int32)), 8, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.circle(overlay, tuple(np.round(goal_xy).astype(np.int32)), 8, (255, 0, 0), 2, cv2.LINE_AA)
    cv2.circle(overlay, tuple(np.round(np.array(trace.snapped_start_px)).astype(np.int32)), 4, (0, 255, 0), -1, cv2.LINE_AA)
    cv2.circle(overlay, tuple(np.round(np.array(trace.snapped_goal_px)).astype(np.int32)), 4, (255, 0, 0), -1, cv2.LINE_AA)
    if trace.points:
        end_point = trace.points[-1]
        cv2.circle(overlay, (int(round(end_point.x_px)), int(round(end_point.y_px))), 5, (255, 0, 255), -1, cv2.LINE_AA)
    return overlay


def save_trace_points(path: Path, trace: TraceResult) -> None:
    lines = ["index\tx_px\ty_px\tx_cm\ty_cm\theading_deg"]
    for point in trace.points:
        lines.append(
            f"{point.index}\t{point.x_px:.3f}\t{point.y_px:.3f}\t{point.x_cm:.4f}\t{point.y_cm:.4f}\t{point.heading_deg:.4f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_confirmed_endpoints(
    trace: TraceResult,
    start_cm: tuple[float, float],
    goal_cm: tuple[float, float],
    board_height_cm: float,
    px_per_cm: int,
    eps_cm: float = 1e-6,
) -> tuple[TraceResult, bool, bool]:
    points = list(trace.points)
    inserted_start = False
    appended_goal = False

    def distance_to_cm(point: TracePoint, target_cm: tuple[float, float]) -> float:
        return math.hypot(point.x_cm - target_cm[0], point.y_cm - target_cm[1])

    if not points or distance_to_cm(points[0], start_cm) > eps_cm:
        start_xy = cm_to_image_px(start_cm, board_height_cm, px_per_cm)
        heading_deg = points[0].heading_deg if points else heading_degrees_between(goal_cm, start_cm, 0.0)
        if points:
            heading_deg = heading_degrees_between(start_cm, (points[0].x_cm, points[0].y_cm), heading_deg)
        points.insert(
            0,
            TracePoint(
                index=0,
                x_px=float(start_xy[0]),
                y_px=float(start_xy[1]),
                x_cm=round(start_cm[0], 4),
                y_cm=round(start_cm[1], 4),
                heading_deg=round(heading_deg, 4),
            ),
        )
        inserted_start = True

    if not points or distance_to_cm(points[-1], goal_cm) > eps_cm:
        goal_xy = cm_to_image_px(goal_cm, board_height_cm, px_per_cm)
        heading_deg = heading_degrees_between((points[-1].x_cm, points[-1].y_cm), goal_cm, points[-1].heading_deg)
        points.append(
            TracePoint(
                index=len(points),
                x_px=float(goal_xy[0]),
                y_px=float(goal_xy[1]),
                x_cm=round(goal_cm[0], 4),
                y_cm=round(goal_cm[1], 4),
                heading_deg=round(heading_deg, 4),
            )
        )
        appended_goal = True

    reindexed: list[TracePoint] = []
    for index, point in enumerate(points):
        reindexed.append(
            TracePoint(
                index=index,
                x_px=point.x_px,
                y_px=point.y_px,
                x_cm=point.x_cm,
                y_cm=point.y_cm,
                heading_deg=point.heading_deg,
            )
        )

    travel_cm = 0.0
    for previous, current in zip(reindexed[:-1], reindexed[1:]):
        travel_cm += math.hypot(current.x_cm - previous.x_cm, current.y_cm - previous.y_cm)
    return (
        TraceResult(
            points=reindexed,
            reached_goal=trace.reached_goal,
            goal_distance_px=0.0,
            travel_cm=travel_cm,
            snapped_start_px=trace.snapped_start_px,
            snapped_goal_px=trace.snapped_goal_px,
        ),
        inserted_start,
        appended_goal,
    )


def save_report(
    path: Path,
    trace: TraceResult,
    start_cm: tuple[float, float],
    goal_cm: tuple[float, float],
    board_width_cm: float,
    board_height_cm: float,
    inserted_start_point: bool = False,
    appended_goal_point: bool = False,
) -> None:
    payload = {
        "board": {
            "width_cm": board_width_cm,
            "height_cm": board_height_cm,
        },
        "start_cm": [start_cm[0], start_cm[1]],
        "goal_cm": [goal_cm[0], goal_cm[1]],
        "snapped_start_px": [round(trace.snapped_start_px[0], 3), round(trace.snapped_start_px[1], 3)],
        "snapped_goal_px": [round(trace.snapped_goal_px[0], 3), round(trace.snapped_goal_px[1], 3)],
        "point_count": len(trace.points),
        "travel_cm": trace.travel_cm,
        "reached_goal": trace.reached_goal,
        "goal_distance_px": trace.goal_distance_px,
        "inserted_start_point": inserted_start_point,
        "appended_goal_point": appended_goal_point,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    image_path = Path(args.image_path)
    name = args.name or image_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    start_cm = parse_point_cm(args.start_cm)
    goal_cm = parse_point_cm(args.goal_cm)
    normalized, board_width_cm, board_height_cm, px_per_cm, _board_color = normalize_board_image(args)
    line_mask = extract_black_mask(normalized, args.line_threshold)
    open_erode_size = args.open_erode_size or args.erode_size
    open_dilate_size = args.open_dilate_size or args.dilate_size
    close_dilate_size = args.close_dilate_size or args.dilate_size
    close_erode_size = args.close_erode_size or args.erode_size
    cleaned_mask = clean_mask(
        line_mask,
        open_erode_size=open_erode_size,
        open_dilate_size=open_dilate_size,
        close_dilate_size=close_dilate_size,
        close_erode_size=close_erode_size,
    )
    skeleton_mask = zhang_suen_thinning(cleaned_mask)

    start_xy = cm_to_image_px(start_cm, board_height_cm, px_per_cm)
    goal_xy = cm_to_image_px(goal_cm, board_height_cm, px_per_cm)
    trace = trace_centerline(
        skeleton_mask=skeleton_mask,
        start_xy=start_xy,
        goal_xy=goal_xy,
        board_height_cm=board_height_cm,
        px_per_cm=px_per_cm,
        step_cm=args.step_cm,
        max_step_cm=args.max_step_cm,
        step_tolerance_cm=args.step_tolerance_cm,
        angle_tolerance_deg=args.angle_tolerance_deg,
        goal_tolerance_cm=args.goal_tolerance_cm,
        min_goal_travel_cm=args.min_goal_travel_cm,
        max_points=args.max_points,
        recent_exclusion_points=args.recent_exclusion_points,
    )
    trace, inserted_start_point, appended_goal_point = ensure_confirmed_endpoints(
        trace,
        start_cm=start_cm,
        goal_cm=goal_cm,
        board_height_cm=board_height_cm,
        px_per_cm=px_per_cm,
    )

    overlay = render_overlay(normalized, trace, start_xy, goal_xy)
    cv2.imwrite(str(target / "normalized.png"), normalized)
    cv2.imwrite(str(target / "line_mask.png"), line_mask)
    cv2.imwrite(str(target / "line_mask_cleaned.png"), cleaned_mask)
    cv2.imwrite(str(target / "skeleton_mask.png"), skeleton_mask)
    cv2.imwrite(str(target / "trace_overlay.png"), overlay)
    save_trace_points(target / "trace_points.tsv", trace)
    save_report(
        target / "report.json",
        trace,
        start_cm,
        goal_cm,
        board_width_cm,
        board_height_cm,
        inserted_start_point,
        appended_goal_point,
    )

    if not trace.reached_goal:
        raise RuntimeError(f"goal not reached; last point is {trace.goal_distance_px:.2f}px from goal")


if __name__ == "__main__":
    main()
