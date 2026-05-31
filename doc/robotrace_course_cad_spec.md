# Robotrace Course CAD: 仕様・設計・実装方針

## 1. 目的

ロボトレース競技用コースの図面を作成するための、Python + PySide6 / Qt ベースの簡易2D CADアプリを実装する。

主な目的は、以下を効率よく設計・描画・検査できるようにすることである。

- 板の領域を表す線
- 円弧と直線で構成されたロボトレースライン
- 円弧部分に対応する補助円
- 補助円の中心座標・半径・インデックス・回転方向
- スタート/ゴール区間
- コーナーマーカー、スタート/ゴールマーカー
- コース制約違反の検出と可視化
- SVG / DXF / PDF などへの出力

本アプリでは、ユーザーが直接ラインを編集するのではなく、基本的には **補助円列を編集し、清書ラインを自動生成する** 方式を採用する。

```text
補助円列 = 編集対象の設計データ
清書ライン = 補助円列から生成される派生データ
```

これにより、補助円の移動・半径変更・順序変更・回転方向変更に応じて、コースラインを自動更新できるようにする。

---

## 2. 対象とするロボトレースコースの基本制約

### 2.1 ライン・コース制約

- ライン幅は `1.9 cm`
- コースは閉路
- `1 m` の直線スタート/ゴール区間が存在する
- ライン同士の交差は直交している必要がある
- 交差点の前後 `10 cm` は直線である必要がある
- コース端からラインまで最低 `20 cm` 確保する
  - 練習用コースでは `10 cm` など緩和設定も許容する

### 2.2 マーカー制約

#### コーナーマーカー

- 曲率変化点の左側に配置する
- ライン中心から `7 cm` 離れた点をマーカー中心とする
- マーカー形状は長方形
  - 長辺 `4.0 cm`
  - 短辺 `1.9 cm`
- 長辺はラインに直交する方向

#### スタート/ゴールマーカー

- スタート/ゴール区間の出入り口の右側に配置する
- ライン中心から `7 cm` 離れた点をマーカー中心とする
- マーカー形状は長方形
  - 長辺 `4.0 cm`
  - 短辺 `1.9 cm`
- 長辺はラインに直交する方向

### 2.3 補助円の半径

実作業の都合上、曲率半径は原則として以下のような離散的な候補から選ぶ。

```text
R10, R15, R20, R25, R30, ...
```

ただし、大きなRを使用する場合は、特定の候補から選ぶのではなく、設計都合で任意の半径を指定できてもよい。

---

## 3. 推奨する実装方針

### 3.1 技術スタック

ローカルアプリとして以下を用いる。

```text
Python
PySide6 / Qt
QGraphicsView / QGraphicsScene
```

必要に応じて以下を利用する。

```text
ezdxf      # DXF出力
svgwrite   # SVG出力
shapely    # 交差・距離・領域チェック用。中心線幾何そのものは自前実装推奨
```

### 3.2 内部座標系

内部座標系は通常の数学座標とする。

```text
単位: cm
x: 右向き正
y: 上向き正
```

Qt描画時のみスクリーン座標へ変換する。

```text
screen_x = scale * x + offset_x
screen_y = -scale * y + offset_y
```

描画座標と設計座標を混同しないこと。

### 3.3 アーキテクチャ

QtのGraphicsItemに設計データを直接持たせず、以下のように分離する。

```text
CourseModel
  ↓ solve
CourseSolution
  ↓ render
QGraphicsScene
```

- `CourseModel`
  - ユーザーが編集する一次データ
  - 板サイズ、補助円列、スタート/ゴールヒント、半径候補、設定など

- `CourseSolution`
  - `CourseModel` から生成された清書結果
  - 接線分、円弧、マーカー、検査結果など

- `Renderer`
  - `CourseSolution` を `QGraphicsScene` に描画する
  - SVG/DXF/PDF出力も同じ `CourseSolution` を参照する

---

## 4. GUI機能

### 4.1 基本画面構成

```text
MainWindow
  ├── CourseView : QGraphicsView
  │     └── CourseScene : QGraphicsScene
  ├── CircleTable : QTableWidget
  ├── PropertyPanel
  │     ├── x, y
  │     ├── radius preset
  │     ├── turn CW/CCW
  │     └── tangent choice override
  └── ErrorPanel
```

### 4.2 表示レイヤー

以下のようなレイヤー分けを推奨する。

```text
Layer board
Layer grid
Layer helper circles
Layer helper circle centers
Layer helper circle labels
Layer generated centerline
Layer actual line width
Layer markers
Layer annotations
Layer errors
```

### 4.3 補助円編集機能

最低限、以下を実装する。

- 補助円の追加
- 補助円の削除
- 補助円の順序変更
- 補助円の中心座標編集
  - 数値入力
  - GUIドラッグ
- 半径編集
  - プリセット選択
  - 任意値入力
- 回転方向編集
  - 時計回り `CW`
  - 反時計回り `CCW`
- 補助円のインデックス表示
- 補助円列の接続順を示す薄い矢印または線の表示

### 4.4 スタート/ゴール指定

ユーザーはスタート/ゴールエリアのおおよその中心位置を指定する。

初期実装では、スタート/ゴールヒントは中心点のみでよい。

```text
StartGoalHint:
  x
  y
  length = 100 cm
```

将来的には、スタート/ゴール区間のおおよその向きも指定できるようにしてよい。

---

## 5. データ構造案

### 5.1 基本ベクトル

```python
from dataclasses import dataclass
import math


@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, s: float):
        return Vec2(self.x * s, self.y * s)

    def dot(self, other) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other) -> float:
        return self.x * other.y - self.y * other.x

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self):
        n = self.norm()
        if n == 0:
            raise ValueError("Cannot normalize zero vector")
        return Vec2(self.x / n, self.y / n)
```

### 5.2 補助円

```python
from dataclasses import dataclass
from enum import Enum


class Turn(Enum):
    CW = "cw"
    CCW = "ccw"


@dataclass
class HelperCircle:
    id: int
    x: float          # cm
    y: float          # cm
    r: float          # cm
    turn: Turn
    locked: bool = False

    @property
    def center(self) -> Vec2:
        return Vec2(self.x, self.y)
```

### 5.3 スタート/ゴールヒント

```python
@dataclass
class StartGoalHint:
    x: float
    y: float
    length: float = 100.0

    @property
    def center(self) -> Vec2:
        return Vec2(self.x, self.y)
```

### 5.4 接線分

接線分は、単なる線分ではなく、両側の円における接点を明示的に持つ。

```python
@dataclass
class TangentSegment:
    from_circle_id: int
    to_circle_id: int

    p_from: Vec2       # from circle 上の接点
    p_to: Vec2         # to circle 上の接点

    kind: str          # "outer" or "inner"
    choice: int        # 0 or 1

    @property
    def length(self) -> float:
        return (self.p_to - self.p_from).norm()
```

### 5.5 円弧

```python
@dataclass
class ArcSegment:
    circle_id: int
    center: Vec2
    radius: float
    p_start: Vec2
    p_end: Vec2
    turn: Turn
    angle_rad: float
    length: float
```

### 5.6 検査結果

```python
@dataclass
class ValidationIssue:
    severity: str       # "error" or "warning"
    message: str
    related_circle_ids: list[int]
    related_connection_ids: list[int]
```

### 5.7 コースモデル

```python
@dataclass
class CourseModel:
    board_width_cm: float
    board_height_cm: float
    line_width_cm: float = 1.9
    min_edge_margin_cm: float = 20.0

    radius_presets_cm: list[float] = None
    circles: list[HelperCircle] = None
    start_goal_hint: StartGoalHint | None = None
```

### 5.8 コース解

```python
@dataclass
class CourseSolution:
    tangents: list[TangentSegment | None]
    arcs: list[ArcSegment | None]
    issues: list[ValidationIssue]
```

---

## 6. 接線選択アルゴリズム

### 6.1 基本方針

補助円列を以下のように並べる。

```text
C0, C1, ..., Cn-1
```

これはスタート後に通過する補助円の順序を表す。

コースは閉路なので、接続は以下のようになる。

```text
C0 -> C1 -> C2 -> ... -> Cn-1 -> C0
```

スタート/ゴール区間は、最後の接続

```text
Cn-1 -> C0
```

に対応する接線上に配置する。

### 6.2 接線タイプ

2つの補助円に対して、回転方向の組み合わせから接線タイプを決める。

```text
同じ回転方向:
  外接線

異なる回転方向:
  内接線
```

具体的には、

```text
CW  -> CW   : outer tangent
CCW -> CCW  : outer tangent
CW  -> CCW  : inner tangent
CCW -> CW   : inner tangent
```

この結果、通常は接線候補が2つに絞られる。

### 6.3 スタート/ゴール接線の選択

最初に、`Cn-1 -> C0` の接線候補2つを求める。

そのうち、ユーザーが指定したスタート/ゴールエリア中心 `S` を通る直線に近い候補を採用する。

より具体的には、候補接線を無限直線とみなし、点 `S` からその直線への距離が小さい方を選ぶ。

```python
def point_line_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    ab = b - a
    ap = p - a
    return abs(ab.cross(ap)) / ab.norm()
```

線分への距離ではなく無限直線への距離を用いる。  
これは、スタート/ゴールヒントが接線分の範囲内に厳密に入っていない場合でも、意図した接線を選びやすくするためである。

### 6.4 順次接線選択

スタート/ゴール接線を初期セグメントとして、`C0 -> C1` から順に接線を選択する。

処理の流れは以下。

```text
1. Cn-1 -> C0 のSG接線を決定
2. C0 -> C1 の候補から、C0上でSG接線と自然につながる候補を選択
3. C1 -> C2 の候補から、C1上で直前の接線と自然につながる候補を選択
4. ...
5. Cn-2 -> Cn-1 まで繰り返す
6. 最後に Cn-1 上で Cn-2 -> Cn-1 と SG接線が自然につながるか確認
```

擬似コード:

```python
def solve_tangents(circles: list[HelperCircle],
                   start_goal_hint: StartGoalHint) -> CourseSolution:
    n = len(circles)
    issues = []
    tangents: list[TangentSegment | None] = [None] * n

    if n < 2:
        issues.append(ValidationIssue(
            severity="error",
            message="At least two helper circles are required",
            related_circle_ids=[],
            related_connection_ids=[],
        ))
        return CourseSolution(tangents=tangents, arcs=[], issues=issues)

    # 1. Start/Goal tangent: C[n-1] -> C[0]
    c_last = circles[n - 1]
    c0 = circles[0]

    sg_candidates = tangent_candidates_by_turn(c_last, c0)

    if not sg_candidates:
        issues.append(ValidationIssue(
            severity="error",
            message="No tangent candidate for start-goal segment",
            related_circle_ids=[c_last.id, c0.id],
            related_connection_ids=[n - 1],
        ))
        return CourseSolution(tangents=tangents, arcs=[], issues=issues)

    sg = choose_tangent_closest_to_point(
        sg_candidates,
        start_goal_hint.center,
    )

    tangents[n - 1] = sg
    prev_tangent = sg

    # 2. Sequentially choose C[i] -> C[i+1]
    for i in range(0, n - 1):
        c = circles[i]
        c_next = circles[i + 1]
        candidates = tangent_candidates_by_turn(c, c_next)

        if not candidates:
            issues.append(ValidationIssue(
                severity="error",
                message=f"No tangent candidate between circle {c.id} and {c_next.id}",
                related_circle_ids=[c.id, c_next.id],
                related_connection_ids=[i],
            ))
            continue

        selected = choose_candidate_consistent_with_previous(
            circle=c,
            prev_tangent=prev_tangent,
            candidates=candidates,
        )

        tangents[i] = selected
        prev_tangent = selected

    # 3. Generate arcs and validate final consistency
    arcs, arc_issues = generate_arcs_and_validate(circles, tangents)
    issues.extend(arc_issues)

    return CourseSolution(
        tangents=tangents,
        arcs=arcs,
        issues=issues,
    )
```

### 6.5 「直前の接線とつじつまの合う候補」の定義

`Ci-1 -> Ci` の接線が決まっている状態で、次の `Ci -> Ci+1` の接線候補を選ぶ。

`Ci` 上で、

```text
P_prev = 前の接線が Ci に接する点
P_next = 次の接線候補が Ci に接する点
```

とする。

`Ci.turn` が `CCW` なら、`P_prev` から `P_next` へ反時計回りに進む円弧を描く。  
`Ci.turn` が `CW` なら、時計回りに進む円弧を描く。

候補ごとに円弧長を計算し、自然なものを採用する。

初期実装では、以下の優先順位でよい。

```text
1. 円弧長が正である
2. 円弧長が極端に短すぎない
3. 円弧長がほぼ一周にならない
4. 指定回転方向に沿った円弧長が短い方を選ぶ
```

将来的には、接続ごとに `tangent_choice` を手動で切り替え可能にする。

---

## 7. 円弧生成

各円 `Ci` について、前後の接線から円弧を生成する。

```text
前の接線: C[i-1] -> C[i]
  Ci 上の接点 = prev_tangent.p_to

次の接線: C[i] -> C[i+1]
  Ci 上の接点 = next_tangent.p_from
```

したがって、

```text
arc_start = prev_tangent.p_to
arc_end   = next_tangent.p_from
turn      = circles[i].turn
```

で円弧を定義できる。

### 7.1 角度計算

円周上の点の角度は以下で求める。

```python
def point_angle(center: Vec2, p: Vec2) -> float:
    return math.atan2(p.y - center.y, p.x - center.x)
```

CCW方向の角度差:

```python
def angle_ccw(a: float, b: float) -> float:
    d = b - a
    while d < 0:
        d += 2 * math.pi
    while d >= 2 * math.pi:
        d -= 2 * math.pi
    return d
```

CW方向の角度差:

```python
def angle_cw(a: float, b: float) -> float:
    d = a - b
    while d < 0:
        d += 2 * math.pi
    while d >= 2 * math.pi:
        d -= 2 * math.pi
    return d
```

円弧長:

```python
arc_length = radius * angle_rad
```

### 7.2 円弧の検査

以下を検査する。

- 円弧生成に必要な前後接線が存在するか
- 円弧長が `10 cm` 以下ではないか
- 円弧長がほぼ一周になっていないか
- 最後の円 `Cn-1` について、直前接線とスタート/ゴール接線が自然につながるか

---

## 8. 共通接線計算

### 8.1 接線計算の入出力

```python
def tangent_candidates_by_turn(
    c1: HelperCircle,
    c2: HelperCircle,
) -> list[TangentSegment]:
    ...
```

戻り値は、回転方向に応じた接線候補2本程度とする。

### 8.2 内接線・外接線の考え方

2円の接線は最大4本存在する。

ただし、回転方向に応じて、

```text
外接線候補2本
または
内接線候補2本
```

に絞る。

実装上は、一般的な2円共通接線計算関数を用意し、内接線の場合は第2円の半径の符号を反転させる方法が使える。

```text
outer tangent:
  r2_eff = r2

inner tangent:
  r2_eff = -r2
```

### 8.3 注意点

接線が存在しない場合がある。

例:

- 内接線が必要だが、円同士が重なっている
- 外接線が必要だが、一方の円が他方に完全に含まれている
- 中心が一致している

この場合、該当する補助円または接続をエラー表示する。

---

## 9. スタート/ゴール区間生成

スタート/ゴール区間は、採用された `Cn-1 -> C0` の接線上に作る。

1. ユーザー指定の中心 `S` を接線の無限直線上に射影する
2. 射影点 `S_projected` をスタート/ゴール区間の中心とする
3. 接線方向ベクトル `t` を用いて、長さ `100 cm` の区間を作る

```python
def project_point_to_line(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    ab = b - a
    t = (p - a).dot(ab) / ab.dot(ab)
    return a + ab * t
```

```python
sg_center = project_point_to_line(S, tangent.p_from, tangent.p_to)
dir = (tangent.p_to - tangent.p_from).normalized()

sg_a = sg_center - dir * 50.0
sg_b = sg_center + dir * 50.0
```

検査:

- 接線分長が `100 cm` 未満ならエラー
- `sg_a`, `sg_b` が接点間の範囲から大きくはみ出す場合はエラー
- スタート/ゴール区間の前後に十分な直線があるか検査する

---

## 10. マーカー生成

### 10.1 法線ベクトル

ライン接線方向の単位ベクトルを

```text
t = (tx, ty)
```

とすると、左法線と右法線は以下。

```text
left  = (-ty, tx)
right = (ty, -tx)
```

### 10.2 コーナーマーカー

曲率変化点において、進行方向の左側に配置する。

```python
marker_center = point_on_line + left_normal * 7.0
```

### 10.3 スタート/ゴールマーカー

スタート/ゴール区間の出入り口において、進行方向の右側に配置する。

```python
marker_center = point_on_line + right_normal * 7.0
```

### 10.4 マーカー形状

- 長辺 `4.0 cm`
- 短辺 `1.9 cm`
- 長辺はラインに直交する方向
- 短辺はライン方向

ローカル座標で4頂点を作り、接線方向・法線方向に変換して配置する。

---

## 11. 検査項目

MVPで実装する検査:

- 補助円数が2未満
- 接線候補が存在しない
- 接線分長が `10 cm` 以下
- 円弧長が `10 cm` 以下
- スタート/ゴール接線長が `100 cm` 未満
- 最後の円弧がスタート/ゴール接線と自然につながらない
- 必要な前後接線が欠落している

将来的に実装する検査:

- 板端からラインまで `20 cm` 未満
- 練習モードでは板端からラインまで `10 cm` 未満
- ライン同士の交差角が直交していない
- 交差点前後 `10 cm` が直線でない
- マーカーが板外にはみ出す
- ライン同士が近すぎる
- 補助円同士の配置が不自然
- 円弧がほぼ一周している
- スタート/ゴール区間が接線分の外にはみ出している

---

## 12. MVP仕様

最初に実装する最小構成。

### 12.1 入力・編集

- 板サイズ指定
- 補助円列の追加・削除・順序変更
- 補助円の中心座標編集
- 補助円の半径編集
- 補助円の回転方向編集
- スタート/ゴール中心点指定

### 12.2 自動生成

- `Cn-1 -> C0` のスタート/ゴール接線選択
- `C0 -> C1 -> ... -> Cn-1` の順次接線選択
- 各補助円上の円弧生成
- ライン中心線生成
- ライン幅 `1.9 cm` 表示
- スタート/ゴール `1 m` 区間表示

### 12.3 表示

- 板領域
- 補助円
- 補助円中心
- 補助円インデックス
- 補助円の回転方向
- 接線分
- 円弧
- ライン幅付き表示
- エラー表示

### 12.4 出力

MVPではSVG出力を優先する。

DXF/PDF出力は後回しでよい。

---

## 13. 後回しにする機能

以下はMVP後に実装する。

- 既存円に接する円のGUI配置
- 2つの円に接する円のGUI配置
- 接線候補の手動切り替え
- Undo / Redo
- グリッドスナップ
- 座標スナップ
- DXF出力
- PDF出力
- 交差点の直交チェック
- 交差点前後10cm直線チェック
- 板端20cmチェック
- マーカー自動配置
- 寸法線
- 図面用注釈
- 補助円一覧のCSV/JSON入出力

---

## 14. 補助円配置支援の将来仕様

### 14.1 任意配置

- 半径を選択して、GUI上で中心をクリックして配置する

### 14.2 既存円に接する円の配置

- 既存円を選択
- 新しい円の半径を選択
- 外接/内接候補を表示
- マウス位置に近い候補を選択して配置

### 14.3 2つの円に接する円の配置

半径 `r` が既知の場合、新しい円の中心 `P` は以下を満たす。

```text
|P - C1| = R1 ± r
|P - C2| = R2 ± r
```

これは2つの円の交点問題に落とせる。

候補点が複数出るため、GUI上で候補を薄く表示し、ユーザーが選択する方式が望ましい。

---

## 15. 保存形式

内部保存にはJSONを用いる。

例:

```json
{
  "board": {
    "width_cm": 360,
    "height_cm": 180
  },
  "line_width_cm": 1.9,
  "min_edge_margin_cm": 20.0,
  "radius_presets_cm": [10, 15, 20, 25, 30],
  "start_goal_hint": {
    "x": 50,
    "y": 30,
    "length": 100
  },
  "circles": [
    {"id": 0, "x": 50, "y": 50, "r": 20, "turn": "ccw"},
    {"id": 1, "x": 100, "y": 80, "r": 15, "turn": "cw"},
    {"id": 2, "x": 150, "y": 50, "r": 25, "turn": "ccw"}
  ]
}
```

---

## 16. 実装時の注意

### 16.1 接線選択は完全自動にしすぎない

MVPでは自動選択のみでよいが、将来的には接続ごとに接線候補を手動で反転できるようにする。

理由:

- 接線候補は幾何的に複数存在する
- 「自然な接続」は人間の意図に依存する
- 大きく回り込む円弧が正しい場合もあり得る

### 16.2 円弧長最小だけでは不十分

初期実装では円弧長が短い候補を選んでよいが、競技コースでは長い円弧が意図される場合もある。

したがって、将来的には以下を導入する。

- 接線候補手動切替
- 円弧候補手動切替
- 接続ごとのロック
- エラーではなく警告として扱うモード

### 16.3 描画と幾何を分離する

Qtの描画結果を設計データとして扱わない。

設計データは常に `CourseModel` にあり、描画はそこから生成する。

### 16.4 単位はcmに統一する

競技仕様や図面作業の都合上、内部単位はcmで統一する。

SVG/DXF出力時に必要ならmmへ変換する。

---

## 17. 推奨ディレクトリ構成

```text
robotrace_course_cad/
  pyproject.toml
  README.md
  src/
    robotrace_course_cad/
      __init__.py

      main.py

      model/
        __init__.py
        geometry.py
        course_model.py
        course_solution.py
        validation.py

      solver/
        __init__.py
        tangents.py
        arcs.py
        markers.py
        course_solver.py

      ui/
        __init__.py
        main_window.py
        course_view.py
        property_panel.py
        circle_table.py
        error_panel.py

      render/
        __init__.py
        qt_renderer.py
        svg_exporter.py
        dxf_exporter.py

      io/
        __init__.py
        json_io.py

  examples/
    sample_course.json

  tests/
    test_geometry.py
    test_tangents.py
    test_arcs.py
    test_course_solver.py
```

---

## 18. テスト方針

まず幾何部分を単体テストする。

### 18.1 Vec2

- 足し算
- 引き算
- 内積
- 外積
- 正規化
- 距離

### 18.2 接線計算

- 同半径2円の外接線
- 異半径2円の外接線
- 同半径2円の内接線
- 異半径2円の内接線
- 接線が存在しないケース
- 中心一致ケース

### 18.3 円弧生成

- CCW 90度円弧
- CW 90度円弧
- 0度付近をまたぐ円弧
- 円弧長10cm以下の警告
- ほぼ一周の検出

### 18.4 コース生成

- 3円の閉路
- 4円の閉路
- スタート/ゴールヒントによる接線選択
- 最終接続の整合性
- 接線分長不足
- 円弧長不足

---

## 19. Codexへの実装指示メモ

最初に以下を実装すること。

1. `geometry.py`
   - `Vec2`
   - 距離、射影、角度、法線などの基本関数

2. `tangents.py`
   - 2円の共通接線候補計算
   - 回転方向に基づく内接線/外接線の選択
   - スタート/ゴールヒントに最も近い接線選択

3. `arcs.py`
   - 接線分列から円弧生成
   - CW/CCWの角度差計算
   - 円弧長計算

4. `course_solver.py`
   - 補助円列から接線分・円弧・検査結果を生成

5. 最小GUI
   - PySide6で板、補助円、接線、円弧を描画
   - JSONを読み込んで表示
   - 最初はGUI編集なしでもよい

6. 次にGUI編集
   - 補助円の追加・削除
   - テーブルから座標・半径・回転方向を編集
   - スタート/ゴールヒントを設定

---

## 20. まとめ

このアプリの核は、一般的なCAD機能ではなく、以下の専用ロジックである。

```text
補助円列
  ↓
スタート/ゴールヒントによる初期接線選択
  ↓
直前接線との整合性による順次接線選択
  ↓
円弧生成
  ↓
競技制約チェック
  ↓
図面出力
```

まずはGUIを作り込む前に、幾何エンジンとSVG出力を安定させる。  
その後にPySide6の編集GUIを載せる。

MVPでは、以下ができれば十分である。

```text
JSONで補助円列を入力
スタート/ゴールヒントを指定
接線・円弧を自動生成
ライン幅付きで描画
明らかなエラーを赤表示
SVG出力
```
