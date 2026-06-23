import csv
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None


# コメント行の判定に使う接頭辞
COMMENT_PREFIXES = ("#", ";", "//")

# ファイル名に使えない禁止文字
INVALID_FILENAME_CHARS = r'<>:"/\\|?*'


def _is_comment_line(stripped_line):
    """行頭の空白を除いた文字列がコメント接頭辞で始まるか判定する。"""
    for prefix in COMMENT_PREFIXES:
        if stripped_line.startswith(prefix):
            return True
    return False


def _parse_csv(csv_path, dedupe_tags):
    """CSVを読み込み、有効なエントリのリストを返す。

    各エントリは dict: {"filename": str, "tags": [str, ...], "line_no": int}
    """
    entries = []

    # UTF-8 BOM付きにも対応するため utf-8-sig で開く
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for line_no, row in enumerate(reader, start=1):
            # 完全な空行はスキップ
            if not row:
                continue

            # コメント判定は最初のセルの行頭空白を除いた文字列で行う
            first_cell = row[0].strip()
            if first_cell == "":
                # 1列目が空＝有効なファイル名がない。
                # ただし全セルが空ならただの空行扱いでスキップする。
                if all(cell.strip() == "" for cell in row):
                    continue
                raise ValueError(
                    "Invalid CSV at line {}: filename is empty.".format(line_no)
                )

            if _is_comment_line(first_cell):
                continue

            filename = first_cell
            raw_tags = [cell.strip() for cell in row[1:]]
            # 空のタグは無視する
            tags = [t for t in raw_tags if t != ""]

            if dedupe_tags:
                seen = set()
                deduped = []
                for t in tags:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                tags = deduped

            entries.append(
                {"filename": filename, "tags": tags, "line_no": line_no}
            )

    return entries


def _resolve_safe_image_path(base_path, filename, line_no):
    """画像パスを解決し、base_path 配下にあることを確認する。"""
    image_path = (base_path / filename).resolve()
    try:
        image_path.relative_to(base_path)
    except ValueError:
        raise ValueError(
            "Unsafe path at line {}: {} is outside {}".format(
                line_no, filename, base_path
            )
        )
    return image_path


def _sanitize_filename_part(text):
    """ファイル名に使う1要素を安全化する。

    - 前後空白を削除
    - 禁止文字・改行・タブを `_` に置換
    - 連続する `_` を1つにまとめる
    - 空になったら空文字を返す（呼び出し側でスキップ）
    """
    if text is None:
        return ""
    text = text.strip()
    if text == "":
        return ""
    # 禁止文字を `_` に置換
    text = re.sub("[{}]".format(re.escape(INVALID_FILENAME_CHARS)), "_", text)
    # 改行・タブなどの空白文字を `_` に置換
    text = re.sub(r"\s", "_", text)
    # 連続する `_` を1つにまとめる
    text = re.sub(r"_+", "_", text)
    # 前後の `_` は削る
    text = text.strip("_")
    return text


def _get_now(timezone):
    """指定タイムゾーンの現在時刻を返す。失敗時はローカル時刻にフォールバック。"""
    if ZoneInfo is not None and timezone:
        try:
            return datetime.now(ZoneInfo(timezone))
        except Exception as e:
            print(
                "[TaggedImageBatchLoader] Invalid timezone '{}': {}. "
                "Falling back to local time.".format(timezone, e)
            )
    return datetime.now()


class TaggedImageBatchLoader:
    # incremental_image モード用の内部カウンタ
    # key = f"{resolved_path}|{csv_filename}|{label}"
    COUNTERS = {}

    # CSVのmtimeキャッシュ: key=(resolved_path_str, csv_filename) → (mtime, entries)
    # ファイルの更新時刻が変わったときだけ再読み込みする
    _CSV_CACHE = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": "/workspace/images"}),
                "csv_filename": ("STRING", {"default": "image_tags.csv"}),
                "mode": (
                    ["random", "incremental_image", "single_image"],
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 18446744073709551615,
                        "control_after_generate": True,
                    },
                ),
                "index": (
                    "INT",
                    {"default": 0, "min": 0, "max": 999999},
                ),
                "label": ("STRING", {"default": "default"}),
                "action_text": ("STRING", {"default": "Dance"}),
                "filename_tag_mode": (
                    ["all", "first_only", "first_two", "none"],
                ),
                "tag_separator": ("STRING", {"default": "_"}),
                "date_folder_format": ("STRING", {"default": "%Y%m%d"}),
                "datetime_format": ("STRING", {"default": "%Y%m%d-%H%M%S"}),
                "timezone": ("STRING", {"default": "Asia/Tokyo"}),
                "missing_file_policy": (
                    ["error", "skip"],
                ),
                "dedupe_tags": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = (
        "IMAGE",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "INT",
    )
    RETURN_NAMES = (
        "image",
        "filename_text",
        "filename_stem",
        "tag_1",
        "tag_2",
        "tags_text",
        "save_prefix",
        "selected_index",
    )
    FUNCTION = "load"
    CATEGORY = "Takuro/Image"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        """キュー投入時に呼ばれる。パスとCSVの存在を早期チェックする。

        path/csv_filename が他ノードに接続されている場合は値が文字列でないため、
        isinstance チェックで非文字列ならスキップして True を返す。
        """
        path = kwargs.get("path")
        csv_filename = kwargs.get("csv_filename")

        if not isinstance(path, str) or not isinstance(csv_filename, str):
            return True

        try:
            base_path = Path(path).resolve()
            if not base_path.exists():
                return "Path does not exist: {}".format(base_path)
            csv_path = os.path.join(str(base_path), csv_filename)
            if not os.path.exists(csv_path):
                return "CSV file does not exist: {}".format(csv_path)
        except Exception as e:
            return str(e)
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # キャッシュで再実行が止まらないよう、毎回違う値を返して常に再実行させる
        return time.time()

    def _build_valid_entries(self, entries, base_path, missing_file_policy):
        """画像存在チェックを行い、有効なエントリだけを返す。"""
        valid = []
        for entry in entries:
            image_path = _resolve_safe_image_path(
                base_path, entry["filename"], entry["line_no"]
            )
            if not image_path.exists():
                if missing_file_policy == "error":
                    raise ValueError(
                        "Missing image file at line {}: {}".format(
                            entry["line_no"], image_path
                        )
                    )
                # skip の場合は候補から除外
                continue
            entry = dict(entry)
            entry["image_path"] = image_path
            valid.append(entry)
        return valid

    def load(
        self,
        path,
        csv_filename,
        mode,
        seed,
        index,
        label,
        action_text,
        filename_tag_mode,
        tag_separator,
        date_folder_format,
        datetime_format,
        timezone,
        missing_file_policy,
        dedupe_tags,
    ):
        # --- パスとCSVの存在確認 ---
        base_path = Path(path).resolve()
        if not base_path.exists():
            raise ValueError("Path does not exist: {}".format(base_path))

        csv_path = os.path.join(str(base_path), csv_filename)
        if not os.path.exists(csv_path):
            raise ValueError("CSV file does not exist: {}".format(csv_path))

        # --- CSV読み込み（mtimeキャッシュ）---
        # ファイルの更新時刻が変わっていなければキャッシュを使い、
        # 変わっていれば（＝ファイルを差し替えた場合）ディスクから再読み込みする。
        cache_key = (str(base_path), csv_filename)
        current_mtime = os.path.getmtime(csv_path)
        cached = self._CSV_CACHE.get(cache_key)
        if cached is not None and cached[0] == current_mtime:
            entries = cached[1]
        else:
            entries = _parse_csv(csv_path, dedupe_tags)
            self._CSV_CACHE[cache_key] = (current_mtime, entries)
        if not entries:
            raise ValueError(
                "No valid entries found in CSV: {}".format(csv_path)
            )

        # --- 画像存在チェック ---
        valid_entries = self._build_valid_entries(
            entries, base_path, missing_file_policy
        )
        if not valid_entries:
            raise ValueError(
                "No existing image files found in CSV: {}".format(csv_path)
            )

        n = len(valid_entries)

        # --- modeごとの選択 ---
        if mode == "random":
            rng = random.Random(seed)
            selected_index = rng.randrange(n)
        elif mode == "single_image":
            selected_index = index % n
        elif mode == "incremental_image":
            counter_key = "{}|{}|{}".format(str(base_path), csv_filename, label)
            if counter_key not in self.COUNTERS:
                # 初回は index を開始位置とする
                selected_index = index % n
                self.COUNTERS[counter_key] = selected_index
            else:
                selected_index = (self.COUNTERS[counter_key] + 1) % n
                self.COUNTERS[counter_key] = selected_index
        else:
            raise ValueError("Unknown mode: {}".format(mode))

        selected = valid_entries[selected_index]
        image_path = selected["image_path"]
        tags = selected["tags"]

        # --- 画像読み込み ---
        try:
            img = Image.open(image_path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
        except Exception as e:
            raise ValueError(
                "Failed to open image at line {}: {} ({})".format(
                    selected["line_no"], image_path, e
                )
            )

        arr = np.array(img).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr)[None,]

        # --- 出力テキスト ---
        filename_text = selected["filename"]
        filename_stem = Path(selected["filename"]).stem
        tag_1 = tags[0] if len(tags) >= 1 else ""
        tag_2 = tags[1] if len(tags) >= 2 else ""
        tags_text = tag_separator.join(tags) if tags else ""

        # --- save_prefix 生成 ---
        save_prefix = self._build_save_prefix(
            tags=tags,
            action_text=action_text,
            filename_tag_mode=filename_tag_mode,
            tag_separator=tag_separator,
            date_folder_format=date_folder_format,
            datetime_format=datetime_format,
            timezone=timezone,
        )

        return (
            tensor,
            filename_text,
            filename_stem,
            tag_1,
            tag_2,
            tags_text,
            save_prefix,
            selected_index,
        )

    def _build_save_prefix(
        self,
        tags,
        action_text,
        filename_tag_mode,
        tag_separator,
        date_folder_format,
        datetime_format,
        timezone,
    ):
        now = _get_now(timezone)
        date_folder = now.strftime(date_folder_format)
        datetime_str = now.strftime(datetime_format)

        # filename_tag_mode に応じて使うタグを決める
        if filename_tag_mode == "all":
            used_tags = list(tags)
        elif filename_tag_mode == "first_only":
            used_tags = tags[:1]
        elif filename_tag_mode == "first_two":
            used_tags = tags[:2]
        elif filename_tag_mode == "none":
            used_tags = []
        else:
            used_tags = list(tags)

        # filename_body の構成要素を順に組み立てる
        parts = []
        for t in used_tags:
            parts.append(t)
        if action_text:
            parts.append(action_text)
        parts.append(datetime_str)

        # 各要素を安全化し、空になったものはスキップ
        safe_parts = []
        for p in parts:
            safe = _sanitize_filename_part(p)
            if safe != "":
                safe_parts.append(safe)

        filename_body = tag_separator.join(safe_parts)

        # date_folder も安全化（区切りの / は残す必要があるため要素単位で処理）
        safe_date_folder = _sanitize_filename_part(date_folder)

        if safe_date_folder:
            return "{}/{}".format(safe_date_folder, filename_body)
        return filename_body
