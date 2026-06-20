# course_image_parser

このサブプロジェクトは、コース図面画像の解析を試すための専用 `uv` 環境を管理します。

## 目的

- OpenCV 系の依存関係を CAD 本体の環境から分離する。
- 既存の `codex_scripts/` はそのまま使う。
	これらのスクリプトは現在 `data/` や `tmp/` をリポジトリルート基準で参照しているためです。

## 環境の作成・更新

リポジトリルートで次を実行します。

```bash
uv sync --project course_image_parser
```

これにより、専用環境が `course_image_parser/.venv` に作成されます。

## 専用環境で既存スクリプトを実行する

既存スクリプトの相対パス前提を保つため、実行はリポジトリルートで行ってください。

```bash
uv run --project course_image_parser python codex_scripts/normalize_course_image.py --help
uv run --project course_image_parser python codex_scripts/rectify_circle_probe.py
```

または、専用環境の Python を直接使っても構いません。

```bash
course_image_parser/.venv/bin/python codex_scripts/normalize_course_image.py --help
```