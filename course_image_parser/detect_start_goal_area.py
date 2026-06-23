#!/usr/bin/env python3
"""Detect start/goal area candidates from course diagram images."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from extract_course_board import (
    PX_PER_CM_DEFAULT,
    OUT_DIR as BOARD_OUT_DIR,
    detect_board,
    parse_board_colors,
    parse_candidate_cell_sizes,
    resolve_board_request,
    warp_board,
)


OUT_DIR = Path("tmp/start_goal_detection")
START_GOAL_LENGTH_CM = 100.0
START_GOAL_LINE_EXTENSION_CM = 10.0
START_GOAL_MARKER_OFFSET_CM = 7.0
START_GOAL_MARKER_LONG_SIDE_CM = 4.0
START_GOAL_MARKER_SHORT_SIDE_CM = 1.9
COURSE_LINE_WIDTH_CM = 1.9
TEMPLATE_MARGIN_CM = 14.0


@dataclass(frozen=True)
class TemplateSpec:
    orientation_deg: int
    template: np.ndarray
    match_mask: np.ndarray
    anchor_px: tuple[int, int]
    segment_start_px: tuple[int, int]
    segment_end_px: tuple[int, int]
    marker0_center_px: tuple[int, int]
    marker1_center_px: tuple[int, int]


@dataclass(frozen=True)
class Candidate:
    orientation_deg: int
    score: float
    bbox: tuple[int, int, int, int]
    segment_start_px: tuple[float, float]
    segment_end_px: tuple[float, float]
    marker0_center_px: tuple[float, float]
    marker1_center_px: tuple[float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--name")
    parser.add_argument("--json-path")
    parser.add_argument("--width-cm", type=float)
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--board-out-dir", default=str(BOARD_OUT_DIR))
    parser.add_argument("--px-per-cm", type=int, default=PX_PER_CM_DEFAULT)
    parser.add_argument("--board-color", default="cyan")
    parser.add_argument("--candidate-cell-sizes", default="135x90,180x90,90x135,90x180")
    parser.add_argument("--black-threshold", type=int, default=120)
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--score-threshold", type=float, default=0.15)
    parser.add_argument("--normalized-input", action="store_true")
    return parser.parse_args()


def dark_response(image: np.ndarray) -> np.ndarray:
    image_f = image.astype(np.float32)
    blackness = (255.0 - image_f.max(axis=2)) / 255.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    response = np.maximum(blackness, binary.astype(np.float32) / 255.0)
    response = cv2.GaussianBlur(response, (0, 0), 1.0)
    if float(response.max()) > 0.0:
        response = response / float(response.max())
    return response.astype(np.float32)


def draw_rotated_rect(
    canvas: np.ndarray,
    center: tuple[float, float],
    tangent: np.ndarray,
    right_side: np.ndarray,
    width_px: float,
    height_px: float,
    value: float,
    thickness_px: int,
) -> None:
    half_width = width_px / 2.0
    half_height = height_px / 2.0
    corners = np.array(
        [
            center - tangent * half_width - right_side * half_height,
            center + tangent * half_width - right_side * half_height,
            center + tangent * half_width + right_side * half_height,
            center - tangent * half_width + right_side * half_height,
        ],
        dtype=np.float32,
    )
    polygon = np.round(corners).astype(np.int32)
    cv2.fillConvexPoly(canvas, polygon, color=value, lineType=cv2.LINE_AA)
    if thickness_px > 0:
        cv2.polylines(canvas, [polygon], isClosed=True, color=value, thickness=thickness_px, lineType=cv2.LINE_AA)


def orientation_vectors(orientation_deg: int) -> tuple[np.ndarray, np.ndarray]:
    if orientation_deg == 0:
        tangent = np.array([1.0, 0.0], dtype=np.float32)
    elif orientation_deg == 90:
        tangent = np.array([0.0, -1.0], dtype=np.float32)
    elif orientation_deg == 180:
        tangent = np.array([-1.0, 0.0], dtype=np.float32)
    elif orientation_deg == 270:
        tangent = np.array([0.0, 1.0], dtype=np.float32)
    else:
        raise ValueError(f"unsupported orientation: {orientation_deg}")
    right_side = np.array([-tangent[1], tangent[0]], dtype=np.float32)
    return tangent, right_side


def build_template(orientation_deg: int, px_per_cm: int) -> TemplateSpec:
    line_length_px = int(round(START_GOAL_LENGTH_CM * px_per_cm))
    line_extension_px = float(START_GOAL_LINE_EXTENSION_CM * px_per_cm)
    marker_offset_px = float(START_GOAL_MARKER_OFFSET_CM * px_per_cm)
    marker_long_px = float(START_GOAL_MARKER_LONG_SIDE_CM * px_per_cm)
    marker_short_px = float(START_GOAL_MARKER_SHORT_SIDE_CM * px_per_cm)
    line_thickness_px = max(4, int(round(COURSE_LINE_WIDTH_CM * px_per_cm)))
    marker_border_px = max(1, int(round(px_per_cm * 0.35)))
    margin_px = max(20, int(round(px_per_cm * TEMPLATE_MARGIN_CM)))
    span_along_tangent = line_length_px + line_extension_px * 2.0 + marker_short_px + margin_px * 2.0
    span_along_normal = marker_offset_px + marker_long_px / 2.0 + line_thickness_px / 2.0 + margin_px * 2.0
    canvas_size = int(round(max(span_along_tangent, span_along_normal) + margin_px * 2.0))
    canvas = np.zeros((canvas_size, canvas_size), dtype=np.float32)

    tangent, right_side = orientation_vectors(orientation_deg)
    anchor = np.array([canvas_size / 2.0, canvas_size / 2.0], dtype=np.float32)
    start = anchor - tangent * (line_length_px / 2.0)
    end = anchor + tangent * (line_length_px / 2.0)
    marker0 = start + right_side * marker_offset_px
    marker1 = end + right_side * marker_offset_px
    line_draw_start = start - tangent * line_extension_px
    line_draw_end = end + tangent * line_extension_px

    cv2.line(
        canvas,
        tuple(np.round(line_draw_start).astype(np.int32)),
        tuple(np.round(line_draw_end).astype(np.int32)),
        0.45,
        thickness=line_thickness_px,
        lineType=cv2.LINE_AA,
    )
    draw_rotated_rect(
        canvas,
        marker0,
        tangent,
        right_side,
        marker_short_px,
        marker_long_px,
        value=1.0,
        thickness_px=marker_border_px,
    )
    draw_rotated_rect(
        canvas,
        marker1,
        tangent,
        right_side,
        marker_short_px,
        marker_long_px,
        value=1.0,
        thickness_px=marker_border_px,
    )
    canvas = cv2.GaussianBlur(canvas, (0, 0), 0.9)
    if float(canvas.max()) > 0.0:
        canvas = canvas / float(canvas.max())

    nonzero = np.argwhere(canvas > 0.02)
    y0, x0 = nonzero.min(axis=0).tolist()
    y1, x1 = nonzero.max(axis=0).tolist()
    crop_margin = max(12, int(round(px_per_cm * 10.0)))
    x0 = max(0, x0 - crop_margin)
    y0 = max(0, y0 - crop_margin)
    x1 = min(canvas.shape[1] - 1, x1 + crop_margin)
    y1 = min(canvas.shape[0] - 1, y1 + crop_margin)
    cropped = canvas[y0 : y1 + 1, x0 : x1 + 1].copy()
    match_mask = np.where(cropped > 0.02, 255, 0).astype(np.uint8)
    return TemplateSpec(
        orientation_deg=orientation_deg,
        template=cropped,
        match_mask=match_mask,
        anchor_px=(int(round(anchor[0] - x0)), int(round(anchor[1] - y0))),
        segment_start_px=(int(round(start[0] - x0)), int(round(start[1] - y0))),
        segment_end_px=(int(round(end[0] - x0)), int(round(end[1] - y0))),
        marker0_center_px=(int(round(marker0[0] - x0)), int(round(marker0[1] - y0))),
        marker1_center_px=(int(round(marker1[0] - x0)), int(round(marker1[1] - y0))),
    )


def add_template_images(target: Path, templates: list[TemplateSpec]) -> None:
    for spec in templates:
        image = np.clip(spec.template * 255.0, 0.0, 255.0).astype(np.uint8)
        cv2.imwrite(str(target / f"template_{spec.orientation_deg}.png"), image)
        cv2.imwrite(str(target / f"template_mask_{spec.orientation_deg}.png"), spec.match_mask)


def candidate_from_match(spec: TemplateSpec, score: float, x: int, y: int) -> Candidate:
    def shift(point: tuple[int, int]) -> tuple[float, float]:
        return float(x + point[0]), float(y + point[1])

    return Candidate(
        orientation_deg=spec.orientation_deg,
        score=float(score),
        bbox=(x, y, spec.template.shape[1], spec.template.shape[0]),
        segment_start_px=shift(spec.segment_start_px),
        segment_end_px=shift(spec.segment_end_px),
        marker0_center_px=shift(spec.marker0_center_px),
        marker1_center_px=shift(spec.marker1_center_px),
    )


def non_maximum_suppression(candidates: list[Candidate], min_distance_px: float) -> list[Candidate]:
    kept: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        center_x = (candidate.segment_start_px[0] + candidate.segment_end_px[0]) * 0.5
        center_y = (candidate.segment_start_px[1] + candidate.segment_end_px[1]) * 0.5
        if any(
            ((center_x - (other.segment_start_px[0] + other.segment_end_px[0]) * 0.5) ** 2 + (center_y - (other.segment_start_px[1] + other.segment_end_px[1]) * 0.5) ** 2) ** 0.5
            < min_distance_px
            for other in kept
        ):
            continue
        kept.append(candidate)
    return kept


def match_templates(
    response: np.ndarray,
    templates: list[TemplateSpec],
    max_candidates: int,
    score_threshold: float,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for spec in templates:
        result = cv2.matchTemplate(response, spec.template, cv2.TM_CCORR_NORMED, mask=spec.match_mask)
        if result.size == 0:
            continue
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        flat_order = np.argsort(result.reshape(-1))[::-1]
        per_template_limit = max(max_candidates * 3, 32)
        seen = 0
        for flat_index in flat_order:
            score = float(result.reshape(-1)[flat_index])
            if score < score_threshold:
                break
            y, x = divmod(int(flat_index), result.shape[1])
            candidates.append(candidate_from_match(spec, score, x, y))
            seen += 1
            if seen >= per_template_limit:
                break

    if not candidates:
        return []

    template_diag = max((spec.template.shape[0] ** 2 + spec.template.shape[1] ** 2) ** 0.5 for spec in templates)
    suppressed = non_maximum_suppression(candidates, min_distance_px=template_diag * 0.35)
    return suppressed[:max_candidates]


def normalize_board_image(args: argparse.Namespace) -> tuple[np.ndarray, float, float, int, str]:
    image_path = Path(args.image_path)
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    if args.normalized_input:
        request = resolve_board_request(args, image_path, args.name or image_path.stem)
        width_cm = request.width_cm if request.width_cm is not None else image.shape[1] / args.px_per_cm
        height_cm = request.height_cm if request.height_cm is not None else image.shape[0] / args.px_per_cm
        return image, float(width_cm), float(height_cm), args.px_per_cm, "input"

    request = resolve_board_request(args, image_path, args.name or image_path.stem)
    board_colors = parse_board_colors(args.board_color)
    candidate_cell_sizes = parse_candidate_cell_sizes(args.candidate_cell_sizes)
    requested_size = None
    if request.width_cm is not None and request.height_cm is not None:
        requested_size = (request.width_cm, request.height_cm)
    detection, _masks = detect_board(
        image=image,
        board_colors=board_colors,
        requested_size=requested_size,
        candidate_cell_sizes=candidate_cell_sizes,
        black_threshold=args.black_threshold,
    )
    normalized = warp_board(image, detection.corners, detection.width_cm, detection.height_cm, args.px_per_cm)
    return normalized, detection.width_cm, detection.height_cm, args.px_per_cm, detection.board_color


def to_board_cm(point_px: tuple[float, float], board_height_cm: float, px_per_cm: int) -> tuple[float, float]:
    x_cm = point_px[0] / float(px_per_cm)
    y_cm = board_height_cm - point_px[1] / float(px_per_cm)
    return x_cm, y_cm


def overlay_candidates(image: np.ndarray, candidates: list[Candidate], top_n: int = 12) -> np.ndarray:
    overlay = image.copy()
    colors = [(0, 0, 255), (0, 128, 255), (255, 0, 128), (0, 180, 0)]
    for index, candidate in enumerate(candidates[:top_n]):
        color = colors[index % len(colors)]
        sx, sy = map(int, map(round, candidate.segment_start_px))
        ex, ey = map(int, map(round, candidate.segment_end_px))
        m0x, m0y = map(int, map(round, candidate.marker0_center_px))
        m1x, m1y = map(int, map(round, candidate.marker1_center_px))
        cv2.line(overlay, (sx, sy), (ex, ey), color, 2, cv2.LINE_AA)
        cv2.circle(overlay, (m0x, m0y), 5, color, -1)
        cv2.circle(overlay, (m1x, m1y), 5, color, -1)
        cv2.putText(
            overlay,
            f"{index}:{candidate.orientation_deg} {candidate.score:.2f}",
            (sx + 6, sy - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return overlay


def save_report(
    path: Path,
    image_path: Path,
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: int,
    board_color: str,
    candidates: list[Candidate],
) -> None:
    rows = []
    for index, candidate in enumerate(candidates):
        start_cm = to_board_cm(candidate.segment_start_px, board_height_cm, px_per_cm)
        end_cm = to_board_cm(candidate.segment_end_px, board_height_cm, px_per_cm)
        marker0_cm = to_board_cm(candidate.marker0_center_px, board_height_cm, px_per_cm)
        marker1_cm = to_board_cm(candidate.marker1_center_px, board_height_cm, px_per_cm)
        rows.append(
            {
                "rank": index,
                "orientation_deg": candidate.orientation_deg,
                "score": candidate.score,
                "bbox_px": list(candidate.bbox),
                "segment_start_px": [round(candidate.segment_start_px[0], 2), round(candidate.segment_start_px[1], 2)],
                "segment_end_px": [round(candidate.segment_end_px[0], 2), round(candidate.segment_end_px[1], 2)],
                "marker0_center_px": [round(candidate.marker0_center_px[0], 2), round(candidate.marker0_center_px[1], 2)],
                "marker1_center_px": [round(candidate.marker1_center_px[0], 2), round(candidate.marker1_center_px[1], 2)],
                "segment_start_cm": [round(start_cm[0], 2), round(start_cm[1], 2)],
                "segment_end_cm": [round(end_cm[0], 2), round(end_cm[1], 2)],
                "marker0_center_cm": [round(marker0_cm[0], 2), round(marker0_cm[1], 2)],
                "marker1_center_cm": [round(marker1_cm[0], 2), round(marker1_cm[1], 2)],
            }
        )

    report = {
        "image": str(image_path),
        "board_color": board_color,
        "board_cm": [board_width_cm, board_height_cm],
        "px_per_cm": px_per_cm,
        "cm_per_px": 1.0 / float(px_per_cm),
        "candidate_count": len(candidates),
        "candidates": rows,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    image_path = Path(args.image_path)
    name = args.name or image_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    normalized, board_width_cm, board_height_cm, px_per_cm, board_color = normalize_board_image(args)
    response = dark_response(normalized)
    templates = [build_template(orientation_deg, px_per_cm) for orientation_deg in (0, 90, 180, 270)]
    candidates = match_templates(response, templates, args.max_candidates, args.score_threshold)

    add_template_images(target, templates)
    cv2.imwrite(str(target / "normalized.png"), normalized)
    cv2.imwrite(str(target / "dark_response.png"), np.clip(response * 255.0, 0.0, 255.0).astype(np.uint8))
    cv2.imwrite(str(target / "candidates.png"), overlay_candidates(normalized, candidates))
    save_report(target / "report.json", image_path, board_width_cm, board_height_cm, px_per_cm, board_color, candidates)


if __name__ == "__main__":
    main()