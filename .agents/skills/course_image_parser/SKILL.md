---
name: course_image_parser
description: "Use when analyzing robotrace course diagram images in this repository to determine board contour, board size, and start/goal candidates by combining scripted detection with AI image analysis and text reading, then stopping for user confirmation before helper-circle extraction or JSON creation."
---

# Course Image Parser

Use this skill in the `robotrace_course_cad` repository when the user wants to read course diagram images such as `data/*.png` and needs a robust first-stage workflow for:

- board contour detection and normalization
- board size identification
- start/goal candidate detection
- cross-checking scripted detections against image text and visual evidence

This skill covers only the first parsing stage. Later stages such as helper-circle extraction, turn-direction confirmation, coordinate completion, and JSON generation are intentionally out of scope for now and should be treated as TBD.

## Stop Rule

After finishing the board analysis and start/goal analysis described below, stop and ask the user how to proceed.

Do not continue to helper-circle ordering, `cw` / `ccw` determination, coordinate completion, or JSON creation unless the user explicitly instructs you to continue after reviewing the intermediate results.

## Environment

From the repository root, prepare the dedicated image-parsing environment if needed.

```bash
uv sync --project course_image_parser
```

Run the analysis tools from the repository root so relative `data/` and `tmp/` paths stay stable.

## Workflow

### 1. Inspect inputs and current artifacts

Identify the target image or image set, then check whether related artifacts already exist.

Look for:

- the source image under `data/`
- a sidecar JSON with known board size, if any
- existing `*_notes.md` files for prior human corrections
- existing outputs under `tmp/extracted_course_boards*` or `tmp/start_goal_detection*`

If the user requested multiple images, decide whether to run them one by one or in batch, but still review findings per image.

### 2. Determine board contour and normalized board image

First obtain a script-based board hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/extract_course_board.py data/<name>.png
```

Use script outputs such as:

- normalized board image
- detected board corners
- board color choice
- estimated board size
- grid period and line positions
- detection report

Then perform AI image analysis on the original image and the normalized result.

Check for visual evidence that supports or contradicts the scripted result:

- outer board frame
- panel seams and panel count
- coordinate axes or dimension labels
- visible grid spacing
- whether the detected corners actually align with the board boundary
- whether the normalized board preserves the expected rectangular geometry

When identifying board size, combine the scripted estimate with image evidence such as:

- explicit width and height labels
- coordinate-range labels
- known board cell dimensions such as 135 x 90 cm or 180 x 90 cm panels
- whether all course elements fit naturally inside the interpreted board

If the script output and visual evidence disagree, do not force a single answer silently. Present the competing interpretations, explain the mismatch, and ask the user which board interpretation should be treated as authoritative.

### 3. Generate start/goal candidates from the normalized board

After the board geometry is good enough to use, obtain a scripted start/goal hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/detect_start_goal_area.py data/<name>.png
```

Treat the scripted detector as a candidate generator, not as the final authority.

Use its outputs to narrow the search space:

- top-ranked candidate segments
- candidate orientation
- marker-center positions
- candidate bounding boxes
- normalized board image with candidate overlays
- template images and score report

### 4. Cross-check start/goal candidates with AI image analysis

For the top candidates, inspect both the full image and focused crops around each candidate.

Use AI image analysis to look for:

- `START`, `GOAL`, or `START/GOAL` text
- coordinate labels near the start/goal area
- marker-like rectangles near the candidate line ends
- a straight segment close to 100 cm long
- entry direction implied by text placement, coordinates, or surrounding course flow
- whether the candidate is near a practical board edge location for race operation

Evaluate the start-area travel direction explicitly instead of assuming it from the text order alone.

- Separate these two questions:
	- which endpoint is labeled `START` and which is labeled `GOAL`
	- which direction the robot actually travels immediately after leaving `START`
- Do not assume that the course direction runs `START -> GOAL` along the marked segment.
- The correct departure direction is always the direction that leaves `START` toward the `GOAL -> START` side of the marked segment.
- Use the neighboring course geometry to decide the departure direction from `START`; the black line connected to the `START` side is more authoritative than the apparent reading order of the text.
- When coordinates are shown for both `START` and `GOAL`, compare the labeled positions with the continuation of the course on both sides of the segment and confirm that the adopted travel direction leaves `START` toward the `GOAL -> START` side.

The scripted detector should reduce the amount of image that needs close inspection. Start from the top-scoring candidates, expand the crop with a generous margin, and read nearby text or symbols before scanning the whole image again.

When image text is visible, compare the text-derived interpretation against the scripted candidate:

- if text gives explicit coordinates, compare them against the candidate segment position after normalization
- if text gives `START` and `GOAL`, determine the endpoint labels first, then separately determine the departure direction from `START`
- if a provisional read suggests `START -> GOAL`, correct it: the adopted travel direction must still leave `START` in the `GOAL -> START` direction, and the note should record that the initial read was rejected
- if marker positions are visible, compare them with the expected side of the detected segment
- if text and geometry disagree, record the disagreement explicitly instead of collapsing them into one answer

When text is weak, partially occluded, or absent, use a confidence statement such as:

- script and image agree strongly
- script geometry is plausible but text evidence is weak
- image text suggests a different location than the scripted top candidate
- multiple candidates remain viable

### 5. Produce a user-facing intermediate report

Before any later-stage parsing, summarize the current state for each image.

Report at least:

- interpreted board size and why
- whether board contour detection looked reliable
- top 1 to 3 start/goal candidates
- evidence used for each candidate
- endpoint labeling and the chosen departure direction from `START`
- any mismatches between scripted detection and image text reading
- what remains uncertain

When available, point the user to generated artifacts such as:

- normalized board image
- board-detection report
- start/goal candidate overlay
- start/goal report JSON

### 6. Mandatory pause

Stop after reporting the intermediate findings.

Ask the user whether to:

1. accept one board interpretation and one start/goal candidate
2. review ambiguous candidates together
3. continue to the later parsing stages once those decisions are fixed

Do not continue automatically past this checkpoint.

## Validation Checklist

Before stopping, make sure all of the following are true:

- board contour was checked by both script output and visual inspection
- board size was justified by either explicit image evidence or a clearly stated inference
- start/goal candidates were generated from the scripted detector
- AI image analysis was used to inspect candidate regions, not only the whole image
- any visible text or coordinate labels were compared against the scripted candidates
- unresolved conflicts were reported to the user
- the workflow stopped before helper-circle extraction or JSON creation

## Notes

- Prefer the dedicated `course_image_parser` environment over the CAD runtime environment for image-analysis work.
- If multiple batch results exist, compare them consistently per image rather than mixing outputs from different runs.
- If a prior `*_notes.md` file exists and the user provides corrections, update that notes file before moving to any later stage.
- Future stages are TBD by design. This skill currently ends after board and start/goal interpretation.
