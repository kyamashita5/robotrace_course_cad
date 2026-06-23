#!/usr/bin/env python3
"""Extract and rectify the board region from a course design image."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


PX_PER_CM_DEFAULT = 4
OUT_DIR = Path("tmp/extracted_course_boards")
KNOWN_CELL_SIZES = (
    (135.0, 90.0),
    (180.0, 90.0),
    (90.0, 135.0),
    (90.0, 180.0),
)


@dataclass(frozen=True)
class BoardRequest:
    name: str
    image_path: Path
    width_cm: float | None
    height_cm: float | None
    size_source: str


@dataclass(frozen=True)
class AxisGridDetection:
    axis_name: str
    raw_projection: np.ndarray
    filtered_projection: np.ndarray
    autocorrelation: np.ndarray
    period_px: float
    offset_px: float
    line_positions: tuple[int, ...]
    autocorrelation_score: float
    comb_score: float


@dataclass(frozen=True)
class BoardDetection:
    board_color: str
    mask: np.ndarray
    corners: np.ndarray
    width_px: float
    height_px: float
    width_cm: float
    height_cm: float
    aspect_penalty: float
    total_score: float
    x_grid: AxisGridDetection
    y_grid: AxisGridDetection
    board_size_hypothesis: dict[str, object]


def load_board_size_from_json(json_path: Path) -> tuple[float, float]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    board = data["board"]
    return float(board["width_cm"]), float(board["height_cm"])


def infer_json_path(image_path: Path, name: str) -> Path:
    image_sidecar = image_path.with_suffix(".json")
    if image_sidecar.exists():
        return image_sidecar
    return Path("data") / f"{name}.json"


def resolve_board_request(args: argparse.Namespace, image_path: Path, name: str) -> BoardRequest:
    if args.width_cm is not None or args.height_cm is not None:
        if args.width_cm is None or args.height_cm is None:
            raise ValueError("--width-cm and --height-cm must be specified together")
        return BoardRequest(name, image_path, float(args.width_cm), float(args.height_cm), "arguments")

    json_path = Path(args.json_path) if args.json_path else infer_json_path(image_path, name)
    if json_path.exists():
        width_cm, height_cm = load_board_size_from_json(json_path)
        return BoardRequest(name, image_path, width_cm, height_cm, f"json:{json_path}")

    return BoardRequest(name, image_path, None, None, "inferred")


def parse_candidate_cell_sizes(raw_value: str) -> list[tuple[float, float]]:
    sizes: list[tuple[float, float]] = []
    for token in raw_value.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if "x" not in token:
            raise ValueError(f"invalid cell size token: {token}")
        width_raw, height_raw = token.split("x", 1)
        sizes.append((float(width_raw), float(height_raw)))
    if not sizes:
        raise ValueError("at least one candidate cell size is required")
    return sizes


def parse_board_colors(raw_value: str) -> list[str]:
    if raw_value == "auto":
        return ["cyan", "black"]

    colors = [token.strip().lower() for token in raw_value.split(",") if token.strip()]
    allowed = {"cyan", "black"}
    invalid = [color for color in colors if color not in allowed]
    if invalid:
        raise ValueError(f"unsupported board colors: {', '.join(invalid)}")
    if not colors:
        raise ValueError("at least one board color is required")
    return colors


def odd_window(size: int) -> int:
    return size if size % 2 == 1 else size + 1


def blur1d(signal: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return signal.copy()
    kernel = np.ones(window, dtype=np.float64) / float(window)
    return np.convolve(signal, kernel, mode="same")


def filter_small_components(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = max(8, int(round(mask.shape[0] * mask.shape[1] * 0.000002)))
    filtered = np.zeros_like(mask)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area >= min_area:
            filtered[labels == label] = 255
    return filtered


def light_refine_mask(mask: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    refined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    refined = cv2.morphologyEx(refined, cv2.MORPH_OPEN, kernel)
    return refined


def cyan_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Tuned from the 2023east diagram, where the board grid cyan is tightly clustered
    # around HSV H=98 with high saturation. For now, keep the decision purely in HSV
    # space so color-threshold behavior can be evaluated independently.
    mask = cv2.inRange(hsv, np.array([94, 90, 160]), np.array([103, 255, 255]))
    return light_refine_mask(mask)


def black_mask(image: np.ndarray, threshold: int) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    dark = gray <= threshold
    low_value = hsv[:, :, 2] <= threshold + 10
    mask = np.where(dark | low_value, 255, 0).astype(np.uint8)
    return refine_mask(mask)


def refine_mask(mask: np.ndarray) -> np.ndarray:
    min_dim = min(mask.shape[:2])
    close_size = odd_window(max(5, int(round(min_dim * 0.012))))
    open_size = odd_window(max(3, int(round(min_dim * 0.004))))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (open_size, open_size))
    refined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
    refined = cv2.morphologyEx(refined, cv2.MORPH_OPEN, open_kernel)
    return refined


def build_mask(image: np.ndarray, board_color: str, black_threshold: int) -> np.ndarray:
    if board_color == "cyan":
        return cyan_mask(image)
    if board_color == "black":
        return black_mask(image, black_threshold)
    raise ValueError(f"unsupported board color: {board_color}")


def preprocess_projection(projection: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    signal = projection.astype(np.float64)
    if signal.size == 0:
        return signal, signal

    length = signal.size
    short_window = odd_window(max(5, int(round(length * 0.004))))
    long_window = odd_window(max(short_window * 7, int(round(length * 0.08))))
    smoothed = blur1d(signal, short_window)
    baseline = blur1d(smoothed, long_window)
    filtered = np.clip(smoothed - baseline, 0.0, None)
    if filtered.max() <= 0.0:
        filtered = smoothed.copy()
    if filtered.max() > 0.0:
        filtered = filtered / filtered.max()
    return smoothed, filtered


def local_maxima(values: np.ndarray) -> np.ndarray:
    if values.size < 3:
        return np.array([], dtype=np.int32)
    maxima = (values[1:-1] >= values[:-2]) & (values[1:-1] >= values[2:])
    return np.flatnonzero(maxima) + 1


def autocorrelate(signal: np.ndarray) -> np.ndarray:
    if signal.size == 0:
        return signal
    centered = signal - float(signal.mean())
    corr = np.correlate(centered, centered, mode="full")[signal.size - 1 :]
    overlap = np.arange(signal.size, 0, -1, dtype=np.float64)
    corr = corr / overlap
    if corr[0] == 0.0:
        return corr
    return corr / corr[0]


def estimate_period(signal: np.ndarray) -> tuple[int, float, np.ndarray]:
    corr = autocorrelate(signal)
    if corr.size < 3:
        raise RuntimeError("projection is too short for autocorrelation")

    length = signal.size
    min_lag = max(10, int(round(length * 0.04)))
    max_lag = min(length - 2, max(min_lag + 1, int(round(length * 0.60))))
    search = corr[min_lag : max_lag + 1]
    peaks = local_maxima(search)

    if peaks.size == 0:
        best_lag = min_lag + int(np.argmax(search))
        return best_lag, float(corr[best_lag]), corr

    candidate_lags = peaks + min_lag
    candidate_scores = corr[candidate_lags]
    peak_max = float(candidate_scores.max())
    strong_mask = candidate_scores >= peak_max * 0.75
    strong_lags = candidate_lags[strong_mask]
    if strong_lags.size == 0:
        best_lag = int(candidate_lags[int(np.argmax(candidate_scores))])
    else:
        best_lag = int(strong_lags.min())
    return best_lag, float(corr[best_lag]), corr


def window_sum(prefix: np.ndarray, start: int, stop: int) -> float:
    return float(prefix[stop] - prefix[start])


def estimate_offset(signal: np.ndarray, period_px: int) -> tuple[int, float]:
    if period_px <= 0:
        raise RuntimeError("period must be positive")

    radius = max(1, int(round(period_px * 0.08)))
    prefix = np.concatenate([[0.0], np.cumsum(signal, dtype=np.float64)])
    best_offset = 0
    best_score = -1.0

    for offset in range(period_px):
        score = 0.0
        for center in range(offset, signal.size, period_px):
            start = max(0, center - radius)
            stop = min(signal.size, center + radius + 1)
            score += window_sum(prefix, start, stop)
        if score > best_score:
            best_score = score
            best_offset = offset

    return best_offset, best_score


def collect_line_positions(signal: np.ndarray, period_px: int, offset_px: int) -> tuple[tuple[int, ...], float, float]:
    radius = max(2, int(round(period_px * 0.18)))
    absolute_threshold = max(0.08, float(signal.max()) * 0.18)
    positions: list[int] = []
    strengths: list[float] = []

    for center in range(offset_px, signal.size + radius, period_px):
        start = max(0, center - radius)
        stop = min(signal.size, center + radius + 1)
        if start >= stop:
            continue
        local = signal[start:stop]
        peak_offset = int(np.argmax(local))
        peak_index = start + peak_offset
        peak_value = float(local[peak_offset])
        if peak_value < absolute_threshold:
            continue
        if positions and abs(peak_index - positions[-1]) <= max(2, radius // 3):
            if peak_value > strengths[-1]:
                positions[-1] = peak_index
                strengths[-1] = peak_value
            continue
        positions.append(peak_index)
        strengths.append(peak_value)

    if len(positions) < 2 and absolute_threshold > 0.03:
        absolute_threshold = 0.03
        positions = []
        strengths = []
        for center in range(offset_px, signal.size + radius, period_px):
            start = max(0, center - radius)
            stop = min(signal.size, center + radius + 1)
            if start >= stop:
                continue
            local = signal[start:stop]
            peak_offset = int(np.argmax(local))
            peak_index = start + peak_offset
            peak_value = float(local[peak_offset])
            if peak_value < absolute_threshold:
                continue
            if positions and abs(peak_index - positions[-1]) <= max(2, radius // 3):
                if peak_value > strengths[-1]:
                    positions[-1] = peak_index
                    strengths[-1] = peak_value
                continue
            positions.append(peak_index)
            strengths.append(peak_value)

    if len(positions) < 2:
        raise RuntimeError("could not find at least two grid lines")

    diffs = np.diff(positions)
    refined_period = float(np.median(diffs)) if diffs.size > 0 else float(period_px)
    strength_score = float(np.mean(strengths)) if strengths else 0.0
    return tuple(int(position) for position in positions), refined_period, strength_score


def detect_axis_grid(projection: np.ndarray, axis_name: str) -> AxisGridDetection:
    raw_projection, filtered_projection = preprocess_projection(projection)
    if filtered_projection.max() <= 0.0:
        raise RuntimeError(f"no usable {axis_name}-axis grid signal found")

    period_px, autocorrelation_score, autocorrelation_curve = estimate_period(filtered_projection)
    offset_px, comb_score = estimate_offset(filtered_projection, period_px)
    line_positions, refined_period, peak_score = collect_line_positions(filtered_projection, period_px, offset_px)

    return AxisGridDetection(
        axis_name=axis_name,
        raw_projection=raw_projection,
        filtered_projection=filtered_projection,
        autocorrelation=autocorrelation_curve,
        period_px=refined_period,
        offset_px=float(line_positions[0]),
        line_positions=line_positions,
        autocorrelation_score=autocorrelation_score,
        comb_score=comb_score * peak_score,
    )


def choose_board_dimensions(
    width_px: float,
    height_px: float,
    x_grid: AxisGridDetection,
    y_grid: AxisGridDetection,
    requested_size: tuple[float, float] | None,
    candidate_cell_sizes: list[tuple[float, float]],
) -> tuple[float, float, float, dict[str, object]]:
    if requested_size is not None:
        ratio = requested_size[0] / max(requested_size[1], 1e-6)
        pixel_ratio = width_px / max(height_px, 1e-6)
        penalty = abs(math.log(max(pixel_ratio, 1e-6) / max(ratio, 1e-6)))
        return requested_size[0], requested_size[1], penalty, {
            "source": "requested_size",
            "selected_board_cm": [requested_size[0], requested_size[1]],
            "pixel_board_ratio": pixel_ratio,
            "selected_board_ratio": ratio,
            "aspect_penalty": penalty,
        }

    cell_ratio_px = x_grid.period_px / max(y_grid.period_px, 1e-6)
    intervals_x = max(1, len(x_grid.line_positions) - 1)
    intervals_y = max(1, len(y_grid.line_positions) - 1)

    best_size = candidate_cell_sizes[0]
    best_penalty = float("inf")
    candidates: list[dict[str, object]] = []
    for cell_width_cm, cell_height_cm in candidate_cell_sizes:
        cell_ratio_cm = cell_width_cm / max(cell_height_cm, 1e-6)
        cell_ratio_penalty = abs(math.log(max(cell_ratio_px, 1e-6) / max(cell_ratio_cm, 1e-6)))
        width_cm = cell_width_cm * intervals_x
        height_cm = cell_height_cm * intervals_y
        board_ratio_px = width_px / max(height_px, 1e-6)
        board_ratio_cm = width_cm / max(height_cm, 1e-6)
        board_ratio_penalty = abs(math.log(max(board_ratio_px, 1e-6) / max(board_ratio_cm, 1e-6)))
        penalty = cell_ratio_penalty + board_ratio_penalty
        candidates.append(
            {
                "cell_cm": [cell_width_cm, cell_height_cm],
                "board_cm": [width_cm, height_cm],
                "cell_ratio_penalty": cell_ratio_penalty,
                "board_ratio_penalty": board_ratio_penalty,
                "total_penalty": penalty,
            }
        )
        if penalty < best_penalty:
            best_penalty = penalty
            best_size = (cell_width_cm, cell_height_cm)

    width_cm = best_size[0] * intervals_x
    height_cm = best_size[1] * intervals_y
    board_ratio_px = width_px / max(height_px, 1e-6)
    board_ratio_cm = width_cm / max(height_cm, 1e-6)
    candidates.sort(key=lambda candidate: float(candidate["total_penalty"]))
    return width_cm, height_cm, best_penalty, {
        "source": "grid_cell_size_hypothesis",
        "selected_cell_cm": [best_size[0], best_size[1]],
        "selected_board_cm": [width_cm, height_cm],
        "grid_intervals": [intervals_x, intervals_y],
        "pixel_cell_ratio": cell_ratio_px,
        "pixel_board_ratio": board_ratio_px,
        "selected_board_ratio": board_ratio_cm,
        "aspect_penalty": best_penalty,
        "candidates": candidates,
    }


def detect_board_from_mask(
    board_color: str,
    mask: np.ndarray,
    requested_size: tuple[float, float] | None,
    candidate_cell_sizes: list[tuple[float, float]],
) -> BoardDetection:
    binary = (mask > 0).astype(np.uint8)
    x_projection = binary.sum(axis=0)
    y_projection = binary.sum(axis=1)

    x_grid = detect_axis_grid(x_projection, "x")
    y_grid = detect_axis_grid(y_projection, "y")

    x0 = float(x_grid.line_positions[0])
    x1 = float(x_grid.line_positions[-1])
    y0 = float(y_grid.line_positions[0])
    y1 = float(y_grid.line_positions[-1])
    width_px = x1 - x0
    height_px = y1 - y0
    if width_px <= 0.0 or height_px <= 0.0:
        raise RuntimeError("detected board bounds are invalid")

    width_cm, height_cm, aspect_penalty, board_size_hypothesis = choose_board_dimensions(
        width_px=width_px,
        height_px=height_px,
        x_grid=x_grid,
        y_grid=y_grid,
        requested_size=requested_size,
        candidate_cell_sizes=candidate_cell_sizes,
    )

    corners = np.array(
        [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        dtype=np.float32,
    )
    total_score = (
        x_grid.autocorrelation_score
        + y_grid.autocorrelation_score
        + 0.0001 * (x_grid.comb_score + y_grid.comb_score)
        - 0.60 * aspect_penalty
    )

    return BoardDetection(
        board_color=board_color,
        mask=mask,
        corners=corners,
        width_px=width_px,
        height_px=height_px,
        width_cm=width_cm,
        height_cm=height_cm,
        aspect_penalty=aspect_penalty,
        total_score=total_score,
        x_grid=x_grid,
        y_grid=y_grid,
        board_size_hypothesis=board_size_hypothesis,
    )


def axis_grid_to_report(grid: AxisGridDetection) -> dict[str, object]:
    return {
        "period_px": float(grid.period_px),
        "offset_px": float(grid.offset_px),
        "line_positions_px": list(grid.line_positions),
        "autocorrelation_score": float(grid.autocorrelation_score),
        "comb_score": float(grid.comb_score),
    }


def detection_to_report(
    request: BoardRequest,
    detection: BoardDetection,
    image: np.ndarray,
    normalized: np.ndarray,
    px_per_cm: int,
    black_threshold: int,
    candidate_cell_sizes: list[tuple[float, float]],
) -> dict[str, object]:
    return {
        "image": str(request.image_path),
        "size_source": request.size_source,
        "board_color": detection.board_color,
        "board_cm": [float(detection.width_cm), float(detection.height_cm)],
        "px_per_cm": px_per_cm,
        "black_threshold": black_threshold,
        "candidate_cell_sizes_cm": [[width, height] for width, height in candidate_cell_sizes],
        "corners_px": detection.corners.tolist(),
        "source_size_px": [int(image.shape[1]), int(image.shape[0])],
        "detected_span_px": [float(detection.width_px), float(detection.height_px)],
        "aspect_penalty": float(detection.aspect_penalty),
        "x_grid": axis_grid_to_report(detection.x_grid),
        "y_grid": axis_grid_to_report(detection.y_grid),
        "total_score": float(detection.total_score),
        "output_size_px": [int(normalized.shape[1]), int(normalized.shape[0])],
        "board_size_hypothesis": detection.board_size_hypothesis,
    }


def detect_board(
    image: np.ndarray,
    board_colors: list[str],
    requested_size: tuple[float, float] | None,
    candidate_cell_sizes: list[tuple[float, float]],
    black_threshold: int,
) -> tuple[BoardDetection, dict[str, np.ndarray]]:
    masks: dict[str, np.ndarray] = {}
    detections: list[BoardDetection] = []
    errors: list[str] = []

    for board_color in board_colors:
        mask = build_mask(image, board_color, black_threshold)
        masks[board_color] = mask
        try:
            detections.append(
                detect_board_from_mask(
                    board_color=board_color,
                    mask=mask,
                    requested_size=requested_size,
                    candidate_cell_sizes=candidate_cell_sizes,
                )
            )
        except RuntimeError as error:
            errors.append(f"{board_color}: {error}")

    if not detections:
        detail = "; ".join(errors) if errors else "no candidate colors were evaluated"
        raise RuntimeError(f"board detection failed: {detail}")

    best_detection = max(detections, key=lambda detection: detection.total_score)
    return best_detection, masks


def warp_board(image: np.ndarray, corners: np.ndarray, width_cm: float, height_cm: float, px_per_cm: int) -> np.ndarray:
    out_width = max(1, int(round(width_cm * px_per_cm)))
    out_height = max(1, int(round(height_cm * px_per_cm)))
    destination = np.array(
        [[0, 0], [out_width - 1, 0], [out_width - 1, out_height - 1], [0, out_height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), destination)
    return cv2.warpPerspective(image, matrix, (out_width, out_height), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))


def overlay_detection(image: np.ndarray, detection: BoardDetection) -> np.ndarray:
    overlay = image.copy()
    points = detection.corners.astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(overlay, [points], isClosed=True, color=(0, 0, 255), thickness=3)

    for x_position in detection.x_grid.line_positions:
        cv2.line(overlay, (x_position, 0), (x_position, overlay.shape[0] - 1), (255, 0, 255), 1)
    for y_position in detection.y_grid.line_positions:
        cv2.line(overlay, (0, y_position), (overlay.shape[1] - 1, y_position), (255, 0, 255), 1)

    for index, point in enumerate(detection.corners.astype(np.int32)):
        cv2.circle(overlay, tuple(point), 6, (0, 165, 255), -1)
        cv2.putText(
            overlay,
            str(index),
            (int(point[0]) + 8, int(point[1]) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 165, 255),
            2,
            cv2.LINE_AA,
        )
    return overlay


def render_projection_plot(
    raw_projection: np.ndarray,
    filtered_projection: np.ndarray,
    line_positions: tuple[int, ...],
) -> np.ndarray:
    width = raw_projection.size
    height = 280
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)

    def signal_to_polyline(signal: np.ndarray, color: tuple[int, int, int], thickness: int) -> None:
        if signal.size == 0:
            return
        max_value = float(signal.max())
        if max_value <= 0.0:
            return
        normalized = signal / max_value
        ys = np.round((height - 20) - normalized * (height - 40)).astype(np.int32)
        xs = np.arange(signal.size, dtype=np.int32)
        points = np.stack([xs, ys], axis=1).reshape((-1, 1, 2))
        cv2.polylines(canvas, [points], isClosed=False, color=color, thickness=thickness)

    signal_to_polyline(raw_projection.astype(np.float64), (180, 180, 180), 1)
    signal_to_polyline(filtered_projection.astype(np.float64), (255, 0, 0), 2)
    for position in line_positions:
        cv2.line(canvas, (position, 0), (position, height - 1), (0, 0, 255), 1)
    return canvas


def process(
    request: BoardRequest,
    out_dir: Path,
    px_per_cm: int,
    board_colors: list[str],
    candidate_cell_sizes: list[tuple[float, float]],
    black_threshold: int,
) -> None:
    image = cv2.imread(str(request.image_path))
    if image is None:
        raise FileNotFoundError(request.image_path)

    requested_size = None
    if request.width_cm is not None and request.height_cm is not None:
        requested_size = (request.width_cm, request.height_cm)

    detection, masks = detect_board(
        image=image,
        board_colors=board_colors,
        requested_size=requested_size,
        candidate_cell_sizes=candidate_cell_sizes,
        black_threshold=black_threshold,
    )

    target = out_dir / request.name
    target.mkdir(parents=True, exist_ok=True)

    normalized = warp_board(image, detection.corners, detection.width_cm, detection.height_cm, px_per_cm)
    selected_mask = masks[detection.board_color]

    cv2.imwrite(str(target / "selected_mask.png"), selected_mask)
    cv2.imwrite(str(target / "detected_board.png"), overlay_detection(image, detection))
    cv2.imwrite(str(target / "normalized.png"), normalized)
    cv2.imwrite(
        str(target / "projection_x.png"),
        render_projection_plot(detection.x_grid.raw_projection, detection.x_grid.filtered_projection, detection.x_grid.line_positions),
    )
    cv2.imwrite(
        str(target / "projection_y.png"),
        render_projection_plot(detection.y_grid.raw_projection, detection.y_grid.filtered_projection, detection.y_grid.line_positions),
    )

    for board_color, mask in masks.items():
        cv2.imwrite(str(target / f"mask_{board_color}.png"), mask)

    report_payload = detection_to_report(
        request=request,
        detection=detection,
        image=image,
        normalized=normalized,
        px_per_cm=px_per_cm,
        black_threshold=black_threshold,
        candidate_cell_sizes=candidate_cell_sizes,
    )
    (target / "report.json").write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (target / "report.txt").open("w", encoding="utf-8") as report:
        report.write(f"image={request.image_path}\n")
        report.write(f"size_source={request.size_source}\n")
        report.write(f"board_color={detection.board_color}\n")
        report.write(f"board_cm=({detection.width_cm},{detection.height_cm})\n")
        report.write(f"board_size_hypothesis_source={detection.board_size_hypothesis.get('source')}\n")
        report.write(f"selected_board_cm={detection.board_size_hypothesis.get('selected_board_cm')}\n")
        report.write(f"selected_cell_cm={detection.board_size_hypothesis.get('selected_cell_cm')}\n")
        report.write(f"grid_intervals={detection.board_size_hypothesis.get('grid_intervals')}\n")
        report.write(f"px_per_cm={px_per_cm}\n")
        report.write(f"black_threshold={black_threshold}\n")
        report.write(f"candidate_cell_sizes_cm={candidate_cell_sizes}\n")
        report.write(f"corners_px={detection.corners.tolist()}\n")
        report.write(f"source_size_px=({image.shape[1]},{image.shape[0]})\n")
        report.write(f"detected_span_px=({detection.width_px:.2f},{detection.height_px:.2f})\n")
        report.write(f"aspect_penalty={detection.aspect_penalty:.6f}\n")
        report.write(f"x_period_px={detection.x_grid.period_px:.3f}\n")
        report.write(f"x_offset_px={detection.x_grid.offset_px:.3f}\n")
        report.write(f"x_lines_px={list(detection.x_grid.line_positions)}\n")
        report.write(f"x_autocorrelation_score={detection.x_grid.autocorrelation_score:.6f}\n")
        report.write(f"x_comb_score={detection.x_grid.comb_score:.6f}\n")
        report.write(f"y_period_px={detection.y_grid.period_px:.3f}\n")
        report.write(f"y_offset_px={detection.y_grid.offset_px:.3f}\n")
        report.write(f"y_lines_px={list(detection.y_grid.line_positions)}\n")
        report.write(f"y_autocorrelation_score={detection.y_grid.autocorrelation_score:.6f}\n")
        report.write(f"y_comb_score={detection.y_grid.comb_score:.6f}\n")
        report.write(f"total_score={detection.total_score:.6f}\n")
        report.write(f"output_size_px=({normalized.shape[1]},{normalized.shape[0]})\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--name")
    parser.add_argument("--json-path")
    parser.add_argument("--width-cm", type=float)
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--px-per-cm", type=int, default=PX_PER_CM_DEFAULT)
    parser.add_argument("--board-color", default="cyan")
    parser.add_argument("--candidate-cell-sizes", default="135x90,180x90,90x135,90x180")
    parser.add_argument("--black-threshold", type=int, default=120)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image_path)
    name = args.name or image_path.stem
    request = resolve_board_request(args, image_path, name)
    board_colors = parse_board_colors(args.board_color)
    candidate_cell_sizes = parse_candidate_cell_sizes(args.candidate_cell_sizes)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    process(
        request=request,
        out_dir=out_dir,
        px_per_cm=args.px_per_cm,
        board_colors=board_colors,
        candidate_cell_sizes=candidate_cell_sizes,
        black_threshold=args.black_threshold,
    )


if __name__ == "__main__":
    main()
