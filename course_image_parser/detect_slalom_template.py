#!/usr/bin/env python3
"""Detect R50/60 cm slalom template candidates from course diagram images."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from detect_start_goal_area import BOARD_OUT_DIR, normalize_board_image, to_board_cm
from trace_centerline_points import extract_black_mask


OUT_DIR = Path("tmp/slalom_template_detection")
RADIUS_CM = 50.0
SPAN_CM = 60.0
LINE_WIDTH_CM = 1.9
MARKER_OFFSET_CM = 7.0
MARKER_NORMAL_CM = 4.0
MARKER_TANGENT_CM = 1.9
TANGENT_PAD_CM = 1.0
NORMAL_PAD_CM = MARKER_OFFSET_CM + MARKER_NORMAL_CM / 2.0 + LINE_WIDTH_CM / 2.0 + 1.2
ENDPOINT_PAD_CM = MARKER_TANGENT_CM / 2.0 + 0.8
KINDS = ("cw-ccw-cw", "ccw-cw-ccw")
ENDPOINT_MARKER_PATTERNS = {
    "endpoints_none": (False, False),
    "endpoint_start": (True, False),
    "endpoint_end": (False, True),
    "endpoints_both": (True, True),
}


@dataclass(frozen=True)
class Template:
    kind: str
    pattern: str
    angle_deg: int
    image: np.ndarray
    mask: np.ndarray
    center_px: tuple[float, float]
    box_px: np.ndarray
    start_px: tuple[float, float]
    end_px: tuple[float, float]
    arc_centers_px: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    path_px: np.ndarray
    marker_centers_px: tuple[tuple[float, float], ...]
    size_cm: tuple[float, float]


@dataclass(frozen=True)
class Match:
    rank: int
    score: float
    kind: str
    pattern: str
    angle_deg: int
    center_px: tuple[float, float]
    center_cm: tuple[float, float]
    start_cm: tuple[float, float]
    end_cm: tuple[float, float]
    arc_centers_cm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    xy_px: tuple[int, int]
    template: Template
    trajectory_trace_hit_ratio: float | None = None
    trajectory_trace_checked_points: int = 0
    marker_black_max_distance_cm: float | None = None
    marker_black_distances_cm: tuple[float, ...] = ()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--name")
    parser.add_argument("--json-path")
    parser.add_argument("--width-cm", type=float)
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--board-out-dir", default=str(BOARD_OUT_DIR))
    parser.add_argument("--px-per-cm", type=int, default=4)
    parser.add_argument("--board-color", default="cyan")
    parser.add_argument("--candidate-cell-sizes", default="135x90,180x90,90x135,90x180")
    parser.add_argument("--black-threshold", type=int, default=120)
    parser.add_argument("--normalized-input", action="store_true")

    parser.add_argument("--line-threshold", type=int, default=150)

    parser.add_argument("--angle-step-deg", type=int, default=10)
    parser.add_argument("--score-threshold", type=float, default=0.20)
    parser.add_argument("--per-template-peaks", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=120)
    parser.add_argument("--nms-distance-cm", type=float, default=8.0)
    parser.add_argument("--nms-angle-deg", type=float, default=25.0)
    parser.add_argument("--chamfer-radius-px", type=int, default=0)
    parser.add_argument("--chamfer-top-n", type=int, default=50)
    parser.add_argument("--trace-points-tsv", help="trace_centerline_points.py trace_points.tsv for trajectory post-filtering")
    parser.add_argument("--trajectory-trace-tolerance-cm", type=float, default=2.0)
    parser.add_argument("--min-trajectory-trace-hit-ratio", type=float, default=0.90)
    parser.add_argument("--marker-black-max-distance-cm", type=float, default=4.0)
    parser.add_argument("--disable-trajectory-post-filter", action="store_true")
    parser.add_argument("--disable-marker-post-filter", action="store_true")
    parser.add_argument("--templates-only", action="store_true")
    return parser.parse_args()


def unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        raise ValueError("zero-length vector")
    return vector / norm


def left_normal(vector: np.ndarray) -> np.ndarray:
    return np.array([-vector[1], vector[0]], dtype=np.float32)


def right_normal(vector: np.ndarray) -> np.ndarray:
    return np.array([vector[1], -vector[0]], dtype=np.float32)


def path_direction(center: np.ndarray, point: np.ndarray, turn: str) -> np.ndarray:
    radius = unit(point - center)
    return left_normal(radius) if turn == "ccw" else right_normal(radius)


def contact_point(c1: np.ndarray, c2: np.ndarray) -> np.ndarray:
    return (c1 + c2) / 2.0


def angle_ccw(a0: float, a1: float) -> float:
    return (a1 - a0) % math.tau


def angle_cw(a0: float, a1: float) -> float:
    return (a0 - a1) % math.tau


def sample_arc(center: np.ndarray, start: np.ndarray, end: np.ndarray, turn: str, count: int = 180) -> np.ndarray:
    a0 = math.atan2(float(start[1] - center[1]), float(start[0] - center[0]))
    a1 = math.atan2(float(end[1] - center[1]), float(end[0] - center[0]))
    if turn == "ccw":
        angles = a0 + np.linspace(0.0, angle_ccw(a0, a1), count)
    else:
        angles = a0 - np.linspace(0.0, angle_cw(a0, a1), count)
    return np.column_stack((center[0] + RADIUS_CM * np.cos(angles), center[1] + RADIUS_CM * np.sin(angles))).astype(np.float32)


def slalom_geometry(kind: str) -> tuple[np.ndarray, tuple[str, str, str], tuple[np.ndarray, np.ndarray, np.ndarray], list[tuple[str, np.ndarray, np.ndarray]]]:
    lateral = math.sqrt((2.0 * RADIUS_CM) ** 2 - (SPAN_CM / 2.0) ** 2)
    if kind == "cw-ccw-cw":
        turns = ("cw", "ccw", "cw")
        centers = (
            np.array([0.0, -RADIUS_CM], dtype=np.float32),
            np.array([SPAN_CM / 2.0, lateral - RADIUS_CM], dtype=np.float32),
            np.array([SPAN_CM, -RADIUS_CM], dtype=np.float32),
        )
    elif kind == "ccw-cw-ccw":
        turns = ("ccw", "cw", "ccw")
        centers = (
            np.array([0.0, RADIUS_CM], dtype=np.float32),
            np.array([SPAN_CM / 2.0, RADIUS_CM - lateral], dtype=np.float32),
            np.array([SPAN_CM, RADIUS_CM], dtype=np.float32),
        )
    else:
        raise ValueError(f"unsupported slalom kind: {kind}")

    start = np.array([0.0, 0.0], dtype=np.float32)
    end = np.array([SPAN_CM, 0.0], dtype=np.float32)
    p12 = contact_point(centers[0], centers[1])
    p23 = contact_point(centers[1], centers[2])
    points = np.vstack(
        (
            sample_arc(centers[0], start, p12, turns[0]),
            sample_arc(centers[1], p12, p23, turns[1]),
            sample_arc(centers[2], p23, end, turns[2]),
        )
    )
    marker_specs = [
        ("endpoint_start", start, np.array([1.0, 0.0], dtype=np.float32)),
        ("center_start", p12, path_direction(centers[0], p12, turns[0])),
        ("center_end", p23, path_direction(centers[1], p23, turns[1])),
        ("endpoint_end", end, np.array([1.0, 0.0], dtype=np.float32)),
    ]
    return points, turns, centers, marker_specs


def rotation_matrix_for_bound(shape: tuple[int, int], angle_deg: float) -> tuple[np.ndarray, tuple[int, int]]:
    height, width = shape
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos_value = abs(matrix[0, 0])
    sin_value = abs(matrix[0, 1])
    new_width = int(height * sin_value + width * cos_value)
    new_height = int(height * cos_value + width * sin_value)
    matrix[0, 2] += new_width / 2.0 - center[0]
    matrix[1, 2] += new_height / 2.0 - center[1]
    return matrix, (new_width, new_height)


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return cv2.transform(points[None, :, :].astype(np.float32), matrix)[0]


def make_template(kind: str, pattern: str, angle_deg: int, px_per_cm: int) -> Template:
    points_cm, _turns, arc_centers_cm, marker_specs = slalom_geometry(kind)
    min_x = float(points_cm[:, 0].min()) - max(TANGENT_PAD_CM, ENDPOINT_PAD_CM)
    max_x = float(points_cm[:, 0].max()) + max(TANGENT_PAD_CM, ENDPOINT_PAD_CM)
    min_y = float(points_cm[:, 1].min()) - NORMAL_PAD_CM
    max_y = float(points_cm[:, 1].max()) + NORMAL_PAD_CM
    width = int(round((max_x - min_x) * px_per_cm)) + 10
    height = int(round((max_y - min_y) * px_per_cm)) + 10
    offset_x = -min_x * px_per_cm + 5.0
    offset_y = -min_y * px_per_cm + 5.0

    image = np.full((height, width), 255, dtype=np.uint8)
    path_px = np.column_stack((points_cm[:, 0] * px_per_cm + offset_x, points_cm[:, 1] * px_per_cm + offset_y)).astype(np.int32)
    cv2.polylines(image, [path_px], False, 0, max(2, int(round(LINE_WIDTH_CM * px_per_cm))), lineType=cv2.LINE_AA)

    endpoint_flags = {
        "endpoint_start": ENDPOINT_MARKER_PATTERNS[pattern][0],
        "endpoint_end": ENDPOINT_MARKER_PATTERNS[pattern][1],
    }
    valid_mask = np.full((height, width), 255, dtype=np.uint8)
    marker_centers_px: list[tuple[float, float]] = []
    for marker_name, marker_point, tangent in marker_specs:
        enabled = True if marker_name.startswith("center_") else endpoint_flags[marker_name]
        if not enabled:
            continue
        tangent_unit = unit(tangent)
        normal = left_normal(tangent_unit)
        center = marker_point + normal * MARKER_OFFSET_CM
        marker_centers_px.append((float(center[0] * px_per_cm + offset_x), float(center[1] * px_per_cm + offset_y)))
        half_normal = MARKER_NORMAL_CM / 2.0
        half_tangent = MARKER_TANGENT_CM / 2.0
        corners = np.array(
            [
                center - normal * half_normal - tangent_unit * half_tangent,
                center - normal * half_normal + tangent_unit * half_tangent,
                center + normal * half_normal + tangent_unit * half_tangent,
                center + normal * half_normal - tangent_unit * half_tangent,
            ],
            dtype=np.float32,
        )
        corners[:, 0] = corners[:, 0] * px_per_cm + offset_x
        corners[:, 1] = corners[:, 1] * px_per_cm + offset_y
        cv2.fillConvexPoly(image, np.round(corners).astype(np.int32), 0, lineType=cv2.LINE_AA)

    if not ENDPOINT_MARKER_PATTERNS[pattern][0]:
        valid_mask[:, : int(round((ENDPOINT_PAD_CM + 0.15) * px_per_cm))] = 0
    if not ENDPOINT_MARKER_PATTERNS[pattern][1]:
        valid_mask[:, -int(round((ENDPOINT_PAD_CM + 0.15) * px_per_cm)) :] = 0

    matrix, size = rotation_matrix_for_bound((height, width), angle_deg)
    rotated = cv2.warpAffine(image, matrix, size, flags=cv2.INTER_LINEAR, borderValue=255)
    border_mask = cv2.warpAffine(np.full((height, width), 255, dtype=np.uint8), matrix, size, flags=cv2.INTER_NEAREST, borderValue=0)
    rotated_valid_mask = cv2.warpAffine(valid_mask, matrix, size, flags=cv2.INTER_NEAREST, borderValue=0)
    mask = cv2.bitwise_and(border_mask, rotated_valid_mask)

    box = transform_points(np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32), matrix)
    rotated_path = transform_points(path_px.astype(np.float32), matrix)
    rotated_marker_centers = transform_points(np.array(marker_centers_px, dtype=np.float32), matrix) if marker_centers_px else np.empty((0, 2), dtype=np.float32)
    key_points_cm = np.array(
        [
            [0.0, 0.0],
            [SPAN_CM, 0.0],
            [SPAN_CM / 2.0, 0.0],
            [arc_centers_cm[0][0], arc_centers_cm[0][1]],
            [arc_centers_cm[1][0], arc_centers_cm[1][1]],
            [arc_centers_cm[2][0], arc_centers_cm[2][1]],
        ],
        dtype=np.float32,
    )
    key_points_px = key_points_cm.copy()
    key_points_px[:, 0] = key_points_px[:, 0] * px_per_cm + offset_x
    key_points_px[:, 1] = key_points_px[:, 1] * px_per_cm + offset_y
    rotated_keys = transform_points(key_points_px, matrix)
    return Template(
        kind=kind,
        pattern=pattern,
        angle_deg=angle_deg,
        image=rotated,
        mask=mask,
        center_px=(float(rotated_keys[2, 0]), float(rotated_keys[2, 1])),
        box_px=box,
        start_px=(float(rotated_keys[0, 0]), float(rotated_keys[0, 1])),
        end_px=(float(rotated_keys[1, 0]), float(rotated_keys[1, 1])),
        arc_centers_px=(
            (float(rotated_keys[3, 0]), float(rotated_keys[3, 1])),
            (float(rotated_keys[4, 0]), float(rotated_keys[4, 1])),
            (float(rotated_keys[5, 0]), float(rotated_keys[5, 1])),
        ),
        path_px=rotated_path,
        marker_centers_px=tuple((float(point[0]), float(point[1])) for point in rotated_marker_centers),
        size_cm=((max_x - min_x), (max_y - min_y)),
    )


def signed_image(gray: np.ndarray) -> np.ndarray:
    return gray.astype(np.float32) / 127.5 - 1.0


def masked_zncc(image: np.ndarray, image2: np.ndarray, template: np.ndarray, mask: np.ndarray) -> np.ndarray:
    template_signed = signed_image(template)
    mask_f = (mask > 0).astype(np.float32)
    sample_count = float(mask_f.sum())
    if sample_count <= 1.0:
        return np.empty((0, 0), dtype=np.float32)
    template_masked = template_signed * mask_f
    sum_template = float(template_masked.sum())
    sum_template2 = float((template_signed * template_signed * mask_f).sum())
    var_template = max(sum_template2 - sum_template * sum_template / sample_count, 1e-6)

    sum_image = cv2.matchTemplate(image, mask_f, cv2.TM_CCORR)
    sum_image2 = cv2.matchTemplate(image2, mask_f, cv2.TM_CCORR)
    sum_image_template = cv2.matchTemplate(image, template_masked, cv2.TM_CCORR)
    numerator = sum_image_template - sum_image * (sum_template / sample_count)
    var_image = np.maximum(sum_image2 - sum_image * sum_image / sample_count, 1e-6)
    scores = numerator / np.sqrt(var_image * var_template)
    return np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)


def make_search_image(normalized: np.ndarray, args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray]:
    line_mask = extract_black_mask(normalized, args.line_threshold)
    search = 255 - line_mask
    return search, line_mask


def point_cm_from_template(local_px: tuple[float, float], xy: tuple[int, int], board_height_cm: float, px_per_cm: int) -> tuple[float, float]:
    return to_board_cm((xy[0] + local_px[0], xy[1] + local_px[1]), board_height_cm, px_per_cm)


def match_from_xy(
    score: float,
    template: Template,
    xy: tuple[int, int],
    board_height_cm: float,
    px_per_cm: int,
) -> Match:
    center_px = (xy[0] + template.center_px[0], xy[1] + template.center_px[1])
    center_cm = to_board_cm(center_px, board_height_cm, px_per_cm)
    start_cm = point_cm_from_template(template.start_px, xy, board_height_cm, px_per_cm)
    end_cm = point_cm_from_template(template.end_px, xy, board_height_cm, px_per_cm)
    arc_centers = tuple(point_cm_from_template(point, xy, board_height_cm, px_per_cm) for point in template.arc_centers_px)
    return Match(
        rank=-1,
        score=float(score),
        kind=template.kind,
        pattern=template.pattern,
        angle_deg=template.angle_deg,
        center_px=(float(center_px[0]), float(center_px[1])),
        center_cm=(float(center_cm[0]), float(center_cm[1])),
        start_cm=(float(start_cm[0]), float(start_cm[1])),
        end_cm=(float(end_cm[0]), float(end_cm[1])),
        arc_centers_cm=arc_centers,  # type: ignore[arg-type]
        xy_px=xy,
        template=template,
    )


def load_trace_points(path: Path) -> np.ndarray:
    rows: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline().strip().split("\t")
        try:
            x_index = header.index("x_cm")
            y_index = header.index("y_cm")
        except ValueError as exc:
            raise ValueError(f"{path} must contain x_cm and y_cm columns") from exc
        for line in handle:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(x_index, y_index):
                continue
            rows.append((float(parts[x_index]), float(parts[y_index])))
    return np.array(rows, dtype=np.float32)


def marker_distance_image_cm(line_mask: np.ndarray, px_per_cm: int) -> np.ndarray:
    black_zero = np.where(line_mask > 0, 0, 255).astype(np.uint8)
    return cv2.distanceTransform(black_zero, cv2.DIST_L2, 3) / float(px_per_cm)


def trace_distance_image_cm(
    trace_points_cm: np.ndarray,
    image_shape: tuple[int, int],
    board_height_cm: float,
    px_per_cm: int,
) -> np.ndarray:
    trace_zero = np.full(image_shape, 255, dtype=np.uint8)
    height, width = image_shape
    for x_cm, y_cm in trace_points_cm:
        x = int(round(float(x_cm) * px_per_cm))
        y = int(round((float(board_height_cm) - float(y_cm)) * px_per_cm))
        if 0 <= x < width and 0 <= y < height:
            trace_zero[y, x] = 0
    return cv2.distanceTransform(trace_zero, cv2.DIST_L2, 3) / float(px_per_cm)


def local_point_distances_from_image_cm(local_px: np.ndarray, xy: tuple[int, int], distance_image_cm: np.ndarray) -> np.ndarray:
    absolute = np.round(local_px).astype(np.int32)
    absolute[:, 0] += int(xy[0])
    absolute[:, 1] += int(xy[1])
    height, width = distance_image_cm.shape
    distances = np.full((absolute.shape[0],), np.inf, dtype=np.float32)
    inside = (absolute[:, 0] >= 0) & (absolute[:, 1] >= 0) & (absolute[:, 0] < width) & (absolute[:, 1] < height)
    distances[inside] = distance_image_cm[absolute[inside, 1], absolute[inside, 0]]
    return distances


def marker_black_distances_cm(match: Match, distance_image_cm: np.ndarray) -> tuple[float, ...]:
    distances: list[float] = []
    height, width = distance_image_cm.shape
    for local_x, local_y in match.template.marker_centers_px:
        x = int(round(match.xy_px[0] + local_x))
        y = int(round(match.xy_px[1] + local_y))
        if x < 0 or y < 0 or x >= width or y >= height:
            distances.append(float("inf"))
        else:
            distances.append(float(distance_image_cm[y, x]))
    return tuple(distances)


def post_filter_matches(
    matches: list[Match],
    trace_distance_cm: np.ndarray | None,
    marker_distance_cm: np.ndarray | None,
    args: argparse.Namespace,
) -> tuple[list[Match], dict[str, object]]:
    accepted: list[Match] = []
    rejected_by_reason = {
        "trajectory_trace_hit_ratio": 0,
        "marker_black_distance": 0,
    }
    for match in matches:
        trajectory_ratio: float | None = None
        trajectory_checked = 0
        marker_distances: tuple[float, ...] = ()
        marker_max: float | None = None

        if trace_distance_cm is not None and not args.disable_trajectory_post_filter:
            distances = local_point_distances_from_image_cm(match.template.path_px, match.xy_px, trace_distance_cm)
            trajectory_checked = int(distances.shape[0])
            trajectory_ratio = float(np.mean(distances <= args.trajectory_trace_tolerance_cm)) if trajectory_checked else 0.0
            if trajectory_ratio < args.min_trajectory_trace_hit_ratio:
                rejected_by_reason["trajectory_trace_hit_ratio"] += 1
                continue

        if marker_distance_cm is not None and not args.disable_marker_post_filter:
            marker_distances = marker_black_distances_cm(match, marker_distance_cm)
            marker_max = max(marker_distances) if marker_distances else None
            if marker_max is not None and marker_max > args.marker_black_max_distance_cm:
                rejected_by_reason["marker_black_distance"] += 1
                continue

        accepted.append(
            replace(
                match,
                trajectory_trace_hit_ratio=trajectory_ratio,
                trajectory_trace_checked_points=trajectory_checked,
                marker_black_max_distance_cm=marker_max,
                marker_black_distances_cm=marker_distances,
            )
        )

    summary = {
        "input_count": len(matches),
        "accepted_count": len(accepted),
        "rejected_count": len(matches) - len(accepted),
        "rejected_by_reason": rejected_by_reason,
        "trajectory_filter": {
            "enabled": trace_distance_cm is not None and not args.disable_trajectory_post_filter,
            "trace_points_tsv": args.trace_points_tsv,
            "tolerance_cm": args.trajectory_trace_tolerance_cm,
            "min_hit_ratio": args.min_trajectory_trace_hit_ratio,
        },
        "marker_filter": {
            "enabled": marker_distance_cm is not None and not args.disable_marker_post_filter,
            "max_distance_cm": args.marker_black_max_distance_cm,
        },
    }
    return accepted, summary


def collect_matches(
    search: np.ndarray,
    templates: list[Template],
    board_height_cm: float,
    px_per_cm: int,
    score_threshold: float,
    per_template_peaks: int,
) -> list[Match]:
    image = signed_image(search)
    image2 = image * image
    matches: list[Match] = []
    for template in templates:
        if template.image.shape[0] > search.shape[0] or template.image.shape[1] > search.shape[1]:
            continue
        scores = masked_zncc(image, image2, template.image, template.mask)
        if scores.size == 0:
            continue
        flat = scores.reshape(-1)
        count = min(max(1, per_template_peaks), flat.size)
        indexes = np.argpartition(flat, -count)[-count:]
        for flat_index in indexes:
            y, x = np.unravel_index(int(flat_index), scores.shape)
            score = float(scores[y, x])
            if score < score_threshold:
                continue
            matches.append(match_from_xy(score, template, (int(x), int(y)), board_height_cm, px_per_cm))
    return matches


def angle_distance_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def suppress_matches(matches: list[Match], max_candidates: int, nms_distance_cm: float, nms_angle_deg: float) -> list[Match]:
    selected: list[Match] = []
    for match in sorted(matches, key=lambda item: item.score, reverse=True):
        duplicate = False
        for other in selected:
            if math.hypot(match.center_cm[0] - other.center_cm[0], match.center_cm[1] - other.center_cm[1]) > nms_distance_cm:
                continue
            if match.kind == other.kind and angle_distance_deg(match.angle_deg, other.angle_deg) <= nms_angle_deg:
                duplicate = True
                break
        if duplicate:
            continue
        selected.append(match)
        if len(selected) >= max_candidates:
            break
    return [
        Match(
            rank=index,
            score=match.score,
            kind=match.kind,
            pattern=match.pattern,
            angle_deg=match.angle_deg,
            center_px=match.center_px,
            center_cm=match.center_cm,
            start_cm=match.start_cm,
            end_cm=match.end_cm,
            arc_centers_cm=match.arc_centers_cm,
            xy_px=match.xy_px,
            template=match.template,
            trajectory_trace_hit_ratio=match.trajectory_trace_hit_ratio,
            trajectory_trace_checked_points=match.trajectory_trace_checked_points,
            marker_black_max_distance_cm=match.marker_black_max_distance_cm,
            marker_black_distances_cm=match.marker_black_distances_cm,
        )
        for index, match in enumerate(selected)
    ]


def mutual_chamfer_cm(search: np.ndarray, match: Match, dx: int, dy: int, px_per_cm: int) -> tuple[float, float, float] | None:
    x = match.xy_px[0] + dx
    y = match.xy_px[1] + dy
    template = match.template.image
    mask = match.template.mask > 0
    height, width = template.shape
    if x < 0 or y < 0 or x + width > search.shape[1] or y + height > search.shape[0]:
        return None
    roi = search[y : y + height, x : x + width]
    template_fg = (template < 128) & mask
    roi_fg = (roi < 128) & mask
    if int(template_fg.sum()) == 0 or int(roi_fg.sum()) == 0:
        return None
    template_zero = np.where(template_fg, 0, 255).astype(np.uint8)
    roi_zero = np.where(roi_fg, 0, 255).astype(np.uint8)
    distance_to_template = cv2.distanceTransform(template_zero, cv2.DIST_L2, 3)
    distance_to_roi = cv2.distanceTransform(roi_zero, cv2.DIST_L2, 3)
    template_to_image = float(distance_to_roi[template_fg].mean() / float(px_per_cm))
    image_to_template = float(distance_to_template[roi_fg].mean() / float(px_per_cm))
    return (template_to_image + image_to_template) / 2.0, template_to_image, image_to_template


def refine_by_chamfer(matches: list[Match], search: np.ndarray, radius_px: int, top_n: int, board_height_cm: float, px_per_cm: int) -> list[dict[str, object]]:
    refined: list[dict[str, object]] = []
    for match in matches[:top_n]:
        best: tuple[float, float, float, int, int] | None = None
        for dy in range(-radius_px, radius_px + 1):
            for dx in range(-radius_px, radius_px + 1):
                result = mutual_chamfer_cm(search, match, dx, dy, px_per_cm)
                if result is None:
                    continue
                chamfer, template_to_image, image_to_template = result
                if best is None or chamfer < best[0]:
                    best = (chamfer, template_to_image, image_to_template, dx, dy)
        if best is None:
            continue
        chamfer, template_to_image, image_to_template, dx, dy = best
        shifted = match_from_xy(match.score, match.template, (match.xy_px[0] + dx, match.xy_px[1] + dy), board_height_cm, px_per_cm)
        refined.append(
            {
                "rank": match.rank,
                "score": match.score,
                "chamfer_cm": chamfer,
                "template_to_image_cm": template_to_image,
                "image_to_template_cm": image_to_template,
                "dx_px": dx,
                "dy_px": dy,
                "center_cm": shifted.center_cm,
                "start_cm": shifted.start_cm,
                "end_cm": shifted.end_cm,
            }
        )
    return refined


def draw_template_box(canvas: np.ndarray, match: Match, color: tuple[int, int, int], dx: int = 0, dy: int = 0) -> None:
    offset = np.array([match.xy_px[0] + dx, match.xy_px[1] + dy], dtype=np.float32)
    points = np.round(match.template.box_px + offset).astype(np.int32)
    cv2.polylines(canvas, [points], True, color, 2, cv2.LINE_AA)


def draw_matches(normalized: np.ndarray, matches: list[Match], top_n: int = 60) -> np.ndarray:
    canvas = normalized.copy()
    colors = {
        "endpoints_none": (100, 100, 100),
        "endpoint_start": (255, 120, 0),
        "endpoint_end": (0, 160, 255),
        "endpoints_both": (0, 0, 255),
    }
    for match in matches[:top_n]:
        color = colors.get(match.pattern, (0, 0, 255))
        draw_template_box(canvas, match, color)
        center = (int(round(match.center_px[0])), int(round(match.center_px[1])))
        cv2.circle(canvas, center, 4, color, -1, cv2.LINE_AA)
        cv2.putText(
            canvas,
            f"{match.rank}:{match.score:.2f} {match.kind} {match.angle_deg}",
            (max(0, match.xy_px[0]), max(16, match.xy_px[1] - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas


def draw_template_sheet(templates: list[Template], path: Path) -> None:
    selected = [template for template in templates if template.angle_deg in (0, 90, 180, 270)]
    cells: list[np.ndarray] = []
    for template in selected:
        vis = cv2.cvtColor(template.image, cv2.COLOR_GRAY2BGR)
        vis[template.mask == 0] = (180, 180, 180)
        scale = min(230.0 / vis.shape[1], 150.0 / vis.shape[0])
        resized = cv2.resize(vis, (max(1, int(vis.shape[1] * scale)), max(1, int(vis.shape[0] * scale))), interpolation=cv2.INTER_NEAREST)
        cell = np.full((190, 250, 3), 255, dtype=np.uint8)
        y = 34 + (150 - resized.shape[0]) // 2
        x = (250 - resized.shape[1]) // 2
        cell[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
        cv2.putText(cell, f"{template.kind} {template.pattern}", (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.putText(cell, f"angle={template.angle_deg}", (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1, cv2.LINE_AA)
        cells.append(cell)
    rows = [np.hstack(cells[index : index + 4]) for index in range(0, len(cells), 4)]
    if rows:
        cv2.imwrite(str(path), np.vstack(rows))


def match_to_row(match: Match) -> dict[str, object]:
    return {
        "rank": match.rank,
        "score": round(match.score, 6),
        "kind": match.kind,
        "turns": match.kind.split("-"),
        "pattern": match.pattern,
        "angle_deg": match.angle_deg,
        "center_cm": [round(match.center_cm[0], 3), round(match.center_cm[1], 3)],
        "start_cm": [round(match.start_cm[0], 3), round(match.start_cm[1], 3)],
        "end_cm": [round(match.end_cm[0], 3), round(match.end_cm[1], 3)],
        "arc_centers_cm": [[round(x, 3), round(y, 3)] for x, y in match.arc_centers_cm],
        "xy_px": [match.xy_px[0], match.xy_px[1]],
        "template_size_px": [int(match.template.image.shape[1]), int(match.template.image.shape[0])],
        "trajectory_trace_hit_ratio": None if match.trajectory_trace_hit_ratio is None else round(match.trajectory_trace_hit_ratio, 6),
        "trajectory_trace_checked_points": match.trajectory_trace_checked_points,
        "marker_black_max_distance_cm": None if match.marker_black_max_distance_cm is None else round(match.marker_black_max_distance_cm, 3),
        "marker_black_distances_cm": [round(value, 3) if math.isfinite(value) else None for value in match.marker_black_distances_cm],
    }


def save_report(
    path: Path,
    image_path: Path,
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: int,
    matches: list[Match],
    refined: list[dict[str, object]],
    post_filter_summary: dict[str, object],
) -> None:
    payload = {
        "image": str(image_path),
        "board_cm": [board_width_cm, board_height_cm],
        "px_per_cm": px_per_cm,
        "slalom": {
            "radius_cm": RADIUS_CM,
            "span_cm": SPAN_CM,
            "circle_count": 3,
        },
        "candidate_count": len(matches),
        "post_filter": post_filter_summary,
        "candidates": [match_to_row(match) for match in matches],
        "chamfer_refined": refined,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_tsv(path: Path, matches: list[Match]) -> None:
    lines = [
        "rank\tscore\tkind\tpattern\tangle_deg\tcenter_x_cm\tcenter_y_cm\tstart_x_cm\tstart_y_cm\tend_x_cm\tend_y_cm\ttrajectory_trace_hit_ratio\tmarker_black_max_distance_cm"
    ]
    for match in matches:
        lines.append(
            "\t".join(
                [
                    str(match.rank),
                    f"{match.score:.6f}",
                    match.kind,
                    match.pattern,
                    str(match.angle_deg),
                    f"{match.center_cm[0]:.3f}",
                    f"{match.center_cm[1]:.3f}",
                    f"{match.start_cm[0]:.3f}",
                    f"{match.start_cm[1]:.3f}",
                    f"{match.end_cm[0]:.3f}",
                    f"{match.end_cm[1]:.3f}",
                    "" if match.trajectory_trace_hit_ratio is None else f"{match.trajectory_trace_hit_ratio:.6f}",
                    "" if match.marker_black_max_distance_cm is None else f"{match.marker_black_max_distance_cm:.3f}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    image_path = Path(args.image_path)
    name = args.name or image_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    normalized, board_width_cm, board_height_cm, px_per_cm, _board_color = normalize_board_image(args)
    if args.angle_step_deg <= 0 or 360 % args.angle_step_deg != 0:
        raise ValueError("--angle-step-deg must be a positive divisor of 360")
    angles = list(range(0, 360, args.angle_step_deg))
    templates = [make_template(kind, pattern, angle, px_per_cm) for kind in KINDS for pattern in ENDPOINT_MARKER_PATTERNS for angle in angles]
    draw_template_sheet(templates, target / "template_sheet.png")
    if args.templates_only:
        print(f"wrote slalom templates to {target}")
        return

    search, line_mask = make_search_image(normalized, args)
    trace_points_cm = load_trace_points(Path(args.trace_points_tsv)) if args.trace_points_tsv else None
    trace_distance_cm = (
        trace_distance_image_cm(trace_points_cm, line_mask.shape, board_height_cm, px_per_cm)
        if trace_points_cm is not None and not args.disable_trajectory_post_filter
        else None
    )
    marker_distance_cm = None if args.disable_marker_post_filter else marker_distance_image_cm(line_mask, px_per_cm)
    raw_matches = collect_matches(
        search=search,
        templates=templates,
        board_height_cm=board_height_cm,
        px_per_cm=px_per_cm,
        score_threshold=args.score_threshold,
        per_template_peaks=args.per_template_peaks,
    )
    filtered_matches, post_filter_summary = post_filter_matches(
        raw_matches,
        trace_distance_cm=trace_distance_cm,
        marker_distance_cm=marker_distance_cm,
        args=args,
    )
    matches = suppress_matches(
        filtered_matches,
        max_candidates=args.max_candidates,
        nms_distance_cm=args.nms_distance_cm,
        nms_angle_deg=args.nms_angle_deg,
    )
    post_filter_summary["nms_output_count"] = len(matches)
    refined: list[dict[str, object]] = []
    if args.chamfer_radius_px > 0:
        refined = refine_by_chamfer(matches, search, args.chamfer_radius_px, args.chamfer_top_n, board_height_cm, px_per_cm)

    cv2.imwrite(str(target / "normalized.png"), normalized)
    cv2.imwrite(str(target / "line_mask.png"), line_mask)
    cv2.imwrite(str(target / "search_input.png"), search)
    cv2.imwrite(str(target / "slalom_candidates.png"), draw_matches(normalized, matches))
    save_report(target / "report.json", image_path, board_width_cm, board_height_cm, px_per_cm, matches, refined, post_filter_summary)
    save_tsv(target / "slalom_candidates.tsv", matches)
    print(
        f"wrote {len(matches)} R50/60 slalom candidates to {target} "
        f"(post-filter accepted {post_filter_summary['accepted_count']}/{post_filter_summary['input_count']})"
    )


if __name__ == "__main__":
    main()
