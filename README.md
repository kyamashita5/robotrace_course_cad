# Robotrace Course CAD

ロボトレース競技コースの設計補助ツールです。

<!--
補助円列を編集し、接線・円弧・マーカーを確認しながら清書用のSVG/PDFを出力するための簡易CADです。

想定ユーザーは、IDEでロボット向けのコードを書いた経験はあるものの、Pythonの環境構築にはあまり慣れていない人です。このREADMEでは、`uv` を使ってプロジェクト専用のPython環境を作る手順を中心に説明します。
-->

## 主な機能
コース形状を円(補助円)の列として管理しており、以下の機能があります。
- 補助円の追加、削除、並べ替え、座標・半径・旋回方向の編集
- マウスドラッグによる補助円の移動
- 前後の円へ接するように補助円位置を補正
  - シケインや蛸壺、S字カーブの設計に便利
- 交差角度などの簡易デザインルールチェック
- JSON形式での保存・読み込み
- 清書版SVG/PDF出力

## 動作に必要なもの

- Python 3.10以上
- uv
- Git

Pythonとuvのインストール方法は環境により変わるため、公式ドキュメントも参照してください。

- Python: https://www.python.org/downloads/
- uv: https://docs.astral.sh/uv/
- Git: https://git-scm.com/downloads

## セットアップ

<details>
<summary>Windows</summary>

PowerShellを開き、適当なフォルダへこのレポジトリをクローンします。

```powershell
cd C:\Users\<ユーザー名>\Dev
git clone https://github.com/kyamashita5/robotrace_course_cad.git
cd robotrace_course_cad
```

Pythonとuvが入っているか確認します。

```powershell
python --version
uv --version
```

仮想環境を作成し、依存ライブラリをインストールします。

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e .
```

PowerShellで `Activate.ps1` が実行できない場合は、以下を一度だけ実行してから、もう一度有効化してください。

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

起動します。

```powershell
robotrace-course-cad
```

サンプルJSONを開いて起動する場合:

```powershell
robotrace-course-cad examples\synthetic\2025alljapan.json
```

</details>

<details>
<summary>Ubuntu</summary>

端末を開き、適当なフォルダへこのレポジトリをクローンします。

```bash
cd ~/dev
git clone https://github.com/kyamashita5/robotrace_course_cad.git
cd robotrace_course_cad
```

Pythonとuvが入っているか確認します。

```bash
python3 --version
uv --version
```

仮想環境を作成し、依存ライブラリをインストールします。

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

起動します。

```bash
robotrace-course-cad
```

サンプルJSONを開いて起動する場合:

```bash
robotrace-course-cad examples/synthetic/2025alljapan.json
```

</details>

<!--
### Ubuntu/WSLでQtが起動しない場合

GUIアプリなので、Linux側でQtの画面表示に必要なパッケージが不足していると起動に失敗することがあります。

Ubuntuでは次を試してください。

```bash
sudo apt update
sudo apt install libxcb-cursor0
```

WSL上で使う場合は、Windows 11のWSLg環境で起動するのが簡単です。`xeyes` などのGUIアプリが表示できる状態なら、このアプリも起動できる可能性が高いです。

Wayland関連で失敗する場合は、以下のようにQtの表示方式を指定すると改善することがあります。

```bash
QT_QPA_PLATFORM=xcb robotrace-course-cad
```
-->

## 基本的な使い方

1. アプリを起動します。
2. 右側の `Helper Circles` テーブルで補助円の座標、半径、旋回方向を編集します。
3. 補助円は左側のキャンバス上でもドラッグして動かせます。
4. `Fit Touch`、`Fit Prev`、`Fit Next` で選択中の補助円を周辺の円へ接する位置に補正できます。
5. `File > Save JSON` または `Save JSON As...` でコースデータを保存します。
6. `File > Export Drawing...` または右側の `Export SVG/PDF...` から清書版を出力します。


<!-- 
## ファイル構成

- `data/`: 手元で作業中のコースデータや出力例
- `examples/`: サンプルコース、テスト用コース
- `examples/synthetic/`: 参照テストに使うコースJSON
- `examples/synthetic_reference/`: 参照テスト用の接線・円弧・補助円データ
- `doc/robotrace_course_cad_spec.md`: 仕様メモ
- `src/robotrace_course_cad/`: アプリ本体
- `tests/`: 自動テスト
-->

## JSONの保存と読み込み

コースデータはJSONで保存されます。代表的な項目は以下です。

- `circles`: 補助円列
- `start_goal_hint`: スタート/ゴール位置のヒント
- `grid`: 板グリッド設定
- `line_width_cm`: ライン幅

既存データを開くには、起動後に `File > Open JSON...` を使うか、起動時にファイル名を指定します。

```bash
robotrace-course-cad examples/synthetic/2025alljapan.json
```

## 清書版の出力

`Export SVG/PDF...` でファイル名を選択します。拡張子で形式が決まります。

- `.svg`: SVGで出力
- `.pdf`: PDFで出力

出力時には、補助円、スタート/ゴールエリア、スタート/ゴールマーカー、コーナーマーカーを印字するか選べます。


<!--
## テスト

開発時の確認には以下を使います。

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Windows PowerShellでは次のように実行できます。

```powershell
$env:QT_QPA_PLATFORM="offscreen"
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## よくあるトラブル

### `robotrace-course-cad` が見つからない

仮想環境が有効になっていない可能性があります。

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Ubuntu:

```bash
source .venv/bin/activate
```

または、仮想環境を有効化せずに以下のように起動できます。

Windows:

```powershell
.\.venv\Scripts\robotrace-course-cad.exe
```

Ubuntu:

```bash
.venv/bin/robotrace-course-cad
```

### `ModuleNotFoundError: No module named 'PySide6'`

依存ライブラリが入っていない可能性があります。

```bash
uv pip install -e .
```

### GUIが起動しない

Ubuntu/WSLではQtの表示関連パッケージが不足している場合があります。まず以下を試してください。

```bash
sudo apt install libxcb-cursor0
```

それでも起動しない場合は、表示環境がGUIアプリを起動できる状態か確認してください。

-->
