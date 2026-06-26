# ComfyUI-Tagged-Image-Batch-Loader

画像フォルダ内の画像を i2v（image-to-video）の起点画像として読み込みつつ、同じフォルダに置いた CSV 設定ファイルから画像ごとのタグを取得し、そのタグを動画保存時の `filename_prefix` に使える文字列（`save_prefix`）として出力する ComfyUI カスタムノードです。

WAS Node Suite などの既存ノードには依存しない、独立した実装です。

## ノード一覧

このリポジトリには 2 つのノードが含まれています。カテゴリはどちらも `taururu/Image` です。

| ノード表示名 | 概要 |
|---|---|
| **Tagged Image Batch Loader** | 画像を 1 枚選択して出力する基本ノード |
| **Tagged Image Dual Loader** | メイン画像とサブ画像（ファイル名 suffix 付き）を同時に出力するノード |

---

## Tagged Image Batch Loader

- CSV に書かれた画像だけを候補にして、1 枚を選択して読み込みます
- 選択画像に紐づくタグを CSV から取得し、保存ファイル名に使える `save_prefix` を生成します

```
[Tagged Image Batch Loader]
    ├─ image       → LTX i2v などの元画像入力
    └─ save_prefix → VHS Video Combine などの filename_prefix
```

## インストール方法

ComfyUI の `custom_nodes` フォルダにこのリポジトリを配置するだけです。追加の pip 依存はありません（Python 標準ライブラリ、PIL、numpy、torch のみ使用）。

```bash
cd <ComfyUI>/custom_nodes
git clone <このリポジトリのURL> ComfyUI-Tagged-Image-Batch-Loader
```

その後 ComfyUI を再起動してください。

### RunPod での配置例

```text
/workspace/runpod-slim/ComfyUI/custom_nodes/ComfyUI-Tagged-Image-Batch-Loader
```

RunPod の初期化ルーチンで上記の場所に `git clone` するだけで利用できます。

## 入力パラメータ一覧

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | STRING | `/workspace/images` | 画像フォルダのパス（絶対パス想定） |
| `csv_filename` | STRING | `image_tags.csv` | `path` 内の CSV 設定ファイル名 |
| `mode` | 選択 | `random` | 画像の選択方法（`random` / `incremental_image` / `single_image`） |
| `seed` | INT | 0 | `random` モードで使う乱数 seed（control_after_generate 対応） |
| `index` | INT | 0 | `single_image` の画像番号（0 始まり）。`incremental_image` では開始位置 |
| `label` | STRING | `default` | `incremental_image` の内部カウンタを区別するラベル |
| `action_text` | STRING | `Dance` | 保存名に含める追加テキスト。空欄なら省略 |
| `filename_tag_mode` | 選択 | `all` | 保存名に含めるタグ（`all` / `first_only` / `first_two` / `none`） |
| `tag_separator` | STRING | `_` | タグや保存名構成要素を結合する区切り文字 |
| `date_folder_format` | STRING | `%Y%m%d` | 出力サブフォルダ名の日時フォーマット |
| `datetime_format` | STRING | `%Y%m%d-%H%M%S` | 保存ファイル名部分の日時フォーマット |
| `timezone` | STRING | `Asia/Tokyo` | 日時生成に使うタイムゾーン（`zoneinfo` 使用） |
| `missing_file_policy` | 選択 | `error` | CSV の画像が存在しない場合（`error` / `skip`） |
| `dedupe_tags` | BOOLEAN | `true` | 同一行内の重複タグを順序保持で除去 |

## 出力一覧

| 出力 | 型 | 説明 |
|---|---|---|
| `image` | IMAGE | 選択された画像（ComfyUI 標準 IMAGE 形式） |
| `filename_text` | STRING | 選択画像のファイル名（拡張子あり） |
| `filename_stem` | STRING | 選択画像の拡張子なしファイル名 |
| `tag_1` | STRING | 1 つ目のタグ。なければ空文字 |
| `tag_2` | STRING | 2 つ目のタグ。なければ空文字 |
| `tags_text` | STRING | 全タグを `tag_separator` で結合した文字列 |
| `save_prefix` | STRING | 保存ノードの `filename_prefix` に渡す文字列 |
| `selected_index` | INT | 選択された CSV エントリの 0 始まり index |

## CSV 仕様

- ヘッダー行はありません
- 1 列目: 画像ファイル名
- 2 列目以降: すべてタグ
- 空行は無視
- コメント行は無視
- UTF-8 / UTF-8 BOM 付きに対応
- CSV として正しくクォートされた値に対応
- 各セルの前後の空白は strip
- 空のタグは無視
- タグが 0 個でもエラーにしません（`tags = []` 扱い）

### コメント行仕様

行頭の空白を除いたあと、以下のいずれかで始まる行はコメント行として無視します。

```text
#
;
//
```

### CSV サンプル

```csv
# filename, character, outfit
x7kMFWfRhAEaJ4uVtz_Ye.jpg,Name-A,Dress
FJ_rHJ5_tmoJZGrdeUblj.jpg,Name-B,Casual

// comment line example
s8OcElHGwg-qx-mgkhcs-.jpg,Name-C,Suit
```

## mode の違い

- **random**: CSV 内の有効な画像から、`seed` を使ってランダムに 1 枚選びます。同じ seed なら同じ画像（決定的）。UI 側で seed を randomize にすれば、Queue ごとに選び直されます。
- **single_image**: `index` で指定した画像を選びます（0 始まり）。件数を超えた場合は剰余で循環します。
- **incremental_image**: 有効な画像を順番に 1 枚ずつ選びます。初回は `index % 件数` から開始し、Queue 実行ごとにカウンタが進みます。最後まで行くと先頭に戻ります。同じ `path` / `csv_filename` / `label` の組でカウンタを管理します。

## save_prefix の出力例

CSV の `x7kMFWfRhAEaJ4uVtz_Ye.jpg,Name-A,Dress` を選択し、`action_text = Dance`、日時が 2026-06-18 15:30:20 の場合：

```text
save_prefix = 20260618/Name-A_Dress_Dance_20260618-153020
```

これを Video Combine 等の `filename_prefix` に接続すると、ComfyUI の output 配下に次のように保存されます。

```text
output/20260618/Name-A_Dress_Dance_20260618-153020.mp4
```

**重要:** `save_prefix` には `output/` を含めません。保存ノードが output 配下に保存する前提のため、相対 prefix として返します。

---

## Tagged Image Dual Loader

全身像と顔のアップなど、**1 エントリにつき 2 枚の画像を同時に出力**したい場合に使うノードです。

CSV は Tagged Image Batch Loader と共通のフォーマットです。CSV の変更は不要で、ファイル名の命名規則だけで 2 枚目を自動取得します。

### ファイル名の命名規則

メイン画像のファイル名（拡張子なし）に `secondary_suffix` を付けたファイルをサブ画像として読み込みます。

```
hogehoge.jpg      → image（メイン）
hogehoge_l.jpg    → image_secondary（サブ）
```

拡張子はメイン画像と同じものが使われます。

### 接続例

```
[Tagged Image Dual Loader]
    ├─ image           → 全身像の入力（LTX i2v など）
    ├─ image_secondary → 顔アップの入力（IPAdapter など）
    └─ save_prefix     → VHS Video Combine などの filename_prefix
```

### 追加パラメータ

Tagged Image Batch Loader の全パラメータに加え、以下が追加されます。

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `secondary_suffix` | STRING | `_l` | メイン画像のステムに付けるサフィックス |
| `missing_secondary_policy` | 選択 | `use_main` | サブ画像が存在しない場合の挙動 |

#### `missing_secondary_policy` の選択肢

| 値 | 挙動 |
|---|---|
| `use_main` | サブ画像がなければ `image_secondary` にメイン画像をそのまま使う |
| `skip` | サブ画像がないエントリを CSV 候補から除外する |
| `error` | サブ画像が見つからなければエラーで停止する |

### 出力一覧

| 出力 | 型 | 説明 |
|---|---|---|
| `image` | IMAGE | メイン画像 |
| `image_secondary` | IMAGE | サブ画像（suffix 付き）。`use_main` 時はメイン画像と同じ |
| `filename_text` | STRING | メイン画像のファイル名（拡張子あり） |
| `filename_stem` | STRING | メイン画像の拡張子なしファイル名 |
| `tag_1` | STRING | 1 つ目のタグ。なければ空文字 |
| `tag_2` | STRING | 2 つ目のタグ。なければ空文字 |
| `tags_text` | STRING | 全タグを `tag_separator` で結合した文字列 |
| `save_prefix` | STRING | 保存ノードの `filename_prefix` に渡す文字列 |
| `selected_index` | INT | 選択された CSV エントリの 0 始まり index |

---

## 既知の制限

- `incremental_image` の内部カウンタは ComfyUI 再起動でリセットされます
- Queue の並列実行時、順序保証は限定的です
- 接続先の保存ノード側が STRING 入力（`filename_prefix`）を受けられる必要があります
