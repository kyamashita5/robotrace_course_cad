# course_image_parser

このサブプロジェクトは、コース図面画像の解析を試すための専用 `uv` 環境を管理します。

## 目的

- OpenCV 系の依存関係を CAD 本体の環境から分離する。
- `course_image_parser/` の画像解析スクリプトを専用環境で実行する。

## 環境の作成・更新

リポジトリルートで次を実行します。

```bash
uv sync --project course_image_parser
```

これにより、専用環境が `course_image_parser/.venv` に作成されます。

## 専用環境で解析スクリプトを実行する

`data/` や `tmp/` の相対パスを安定させるため、実行はリポジトリルートで行ってください。

```bash
uv run --project course_image_parser python course_image_parser/extract_course_board.py --help
```

または、専用環境の Python を直接使っても構いません。

```bash
course_image_parser/.venv/bin/python course_image_parser/extract_course_board.py --help
```

## 画像解析ワークフロー

板領域の切り出しからコースデータ候補の生成までの手順は、
[course-image-parser スキル](../.agents/skills/course-image-parser/SKILL.md)を参照してください。
