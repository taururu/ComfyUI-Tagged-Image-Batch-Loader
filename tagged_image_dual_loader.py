import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

from .tagged_image_batch_loader import (
    _get_now,
    _make_thumb_b64,
    _parse_csv,
    _resolve_safe_image_path,
    _sanitize_filename_part,
    _snapshot_key_base,
    _store_snapshot_to,
)

try:
    from aiohttp import web
    from server import PromptServer
    _SERVER_AVAILABLE = True
except Exception:
    _SERVER_AVAILABLE = False


if _SERVER_AVAILABLE:
    @PromptServer.instance.routes.get("/taururu/dual_loader/preview")
    async def dual_loader_preview(request):
        path             = request.rel_url.query.get("path", "")
        csv_filename     = request.rel_url.query.get("csv_filename", "image_tags.csv")
        secondary_suffix = request.rel_url.query.get("secondary_suffix", "_l")

        try:
            base_path = Path(path).resolve()
            if not base_path.exists():
                return web.json_response(
                    {"error": "Path does not exist: {}".format(base_path)}, status=400
                )
            csv_path = base_path / csv_filename
            if not csv_path.exists():
                return web.json_response(
                    {"error": "CSV not found: {}".format(csv_path)}, status=400
                )
            entries = _parse_csv(str(csv_path), dedupe_tags=True)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

        result = []
        for entry in entries:
            try:
                image_path = _resolve_safe_image_path(
                    base_path, entry["filename"], entry["line_no"]
                )
            except ValueError:
                continue

            stem = image_path.stem
            ext  = image_path.suffix
            secondary_filename = "{}{}{}".format(stem, secondary_suffix, ext)
            secondary_path = base_path / secondary_filename

            main_exists      = image_path.exists()
            secondary_exists = secondary_path.exists()

            result.append({
                "filename":           entry["filename"],
                "secondary_filename": secondary_filename,
                "main_exists":        main_exists,
                "secondary_exists":   secondary_exists,
                "main_thumb":         _make_thumb_b64(image_path)     if main_exists      else None,
                "secondary_thumb":    _make_thumb_b64(secondary_path) if secondary_exists else None,
                "tags":               entry["tags"],
            })

        return web.json_response(result)


class TaggedImageDualLoader:
    """メイン画像とサブ画像（suffix付き）を同時に出力するローダー。

    CSVはTaggedImageBatchLoaderと同じ形式。
    選んだ hogehoge.jpg に加え、hogehoge_l.jpg も自動で読み込む。
    """

    COUNTERS = {}
    _CSV_SNAPSHOTS = {}
    _MAX_SNAPSHOTS = 1000

    @classmethod
    def _snapshot_key(cls, path, csv_filename, mode, seed, index, label, dedupe_tags):
        return _snapshot_key_base(
            path, csv_filename, mode, seed, index, label, dedupe_tags
        )

    @classmethod
    def _store_snapshot(cls, key, entries):
        _store_snapshot_to(cls._CSV_SNAPSHOTS, cls._MAX_SNAPSHOTS, key, entries)

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
                "secondary_suffix": ("STRING", {"default": "_l"}),
                "missing_secondary_policy": (
                    ["use_main", "skip", "error"],
                ),
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
            },
            "optional": {
                "excluded_files": ("STRING", {"default": "[]"}),
            },
        }

    RETURN_TYPES = (
        "IMAGE",
        "IMAGE",
        "STRING",
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
        "image_secondary",
        "filename_text",
        "filename_stem",
        "tag_1",
        "tag_2",
        "tags_text",
        "save_prefix",
        "filename_body",
        "selected_index",
    )
    FUNCTION = "load"
    CATEGORY = "taururu/Image"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        path = kwargs.get("path")
        csv_filename = kwargs.get("csv_filename")

        if not isinstance(path, str) or not isinstance(csv_filename, str):
            return True

        try:
            import os
            base_path = Path(path).resolve()
            if not base_path.exists():
                return "Path does not exist: {}".format(base_path)
            csv_path = os.path.join(str(base_path), csv_filename)
            if not os.path.exists(csv_path):
                return "CSV file does not exist: {}".format(csv_path)

            dedupe_tags = kwargs.get("dedupe_tags", True)
            entries = _parse_csv(csv_path, dedupe_tags)
            key = cls._snapshot_key(
                path,
                csv_filename,
                kwargs.get("mode"),
                kwargs.get("seed"),
                kwargs.get("index"),
                kwargs.get("label"),
                dedupe_tags,
            )
            cls._store_snapshot(key, entries)
        except Exception as e:
            return str(e)
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return time.time()

    def _build_valid_entries(
        self, entries, base_path, missing_file_policy, secondary_suffix, missing_secondary_policy
    ):
        """メイン画像・サブ画像の存在チェックを行い、有効エントリだけを返す。"""
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
                continue

            # サブ画像パスを生成: stem + secondary_suffix + suffix
            stem = image_path.stem
            ext = image_path.suffix
            secondary_filename = "{}{}{}".format(stem, secondary_suffix, ext)
            secondary_path = image_path.parent / secondary_filename

            if not secondary_path.exists():
                if missing_secondary_policy == "error":
                    raise ValueError(
                        "Missing secondary image at line {}: {}".format(
                            entry["line_no"], secondary_path
                        )
                    )
                elif missing_secondary_policy == "skip":
                    continue
                # use_main: secondary_path を None にしてメイン画像で代用
                secondary_path = None

            entry = dict(entry)
            entry["image_path"] = image_path
            entry["secondary_path"] = secondary_path
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
        secondary_suffix,
        missing_secondary_policy,
        action_text,
        filename_tag_mode,
        tag_separator,
        date_folder_format,
        datetime_format,
        timezone,
        missing_file_policy,
        dedupe_tags,
        excluded_files="[]",
    ):
        import os

        base_path = Path(path).resolve()
        if not base_path.exists():
            raise ValueError("Path does not exist: {}".format(base_path))

        csv_path = os.path.join(str(base_path), csv_filename)
        if not os.path.exists(csv_path):
            raise ValueError("CSV file does not exist: {}".format(csv_path))

        key = self._snapshot_key(
            path, csv_filename, mode, seed, index, label, dedupe_tags
        )
        entries = self._CSV_SNAPSHOTS.get(key)
        if entries is None:
            entries = _parse_csv(csv_path, dedupe_tags)
        if not entries:
            raise ValueError(
                "No valid entries found in CSV: {}".format(csv_path)
            )

        try:
            excluded = set(json.loads(excluded_files)) if excluded_files.strip() else set()
        except Exception:
            excluded = set()
        if excluded:
            entries = [e for e in entries if e["filename"] not in excluded]
        if not entries:
            raise ValueError(
                "No entries remain after excluded_files filter."
            )

        valid_entries = self._build_valid_entries(
            entries, base_path, missing_file_policy, secondary_suffix, missing_secondary_policy
        )
        if not valid_entries:
            raise ValueError(
                "No existing image files found in CSV: {}".format(csv_path)
            )

        n = len(valid_entries)

        if mode == "random":
            rng = random.Random(seed)
            selected_index = rng.randrange(n)
        elif mode == "single_image":
            selected_index = index % n
        elif mode == "incremental_image":
            counter_key = "{}|{}|{}".format(str(base_path), csv_filename, label)
            if counter_key not in self.COUNTERS:
                selected_index = index % n
                self.COUNTERS[counter_key] = selected_index
            else:
                selected_index = (self.COUNTERS[counter_key] + 1) % n
                self.COUNTERS[counter_key] = selected_index
        else:
            raise ValueError("Unknown mode: {}".format(mode))

        selected = valid_entries[selected_index]
        image_path = selected["image_path"]
        secondary_path = selected["secondary_path"]  # None なら use_main
        tags = selected["tags"]

        # メイン画像読み込み
        tensor = self._load_image_tensor(image_path, selected["line_no"])

        # サブ画像読み込み（None なら use_main）
        if secondary_path is None:
            tensor_secondary = tensor
        else:
            tensor_secondary = self._load_image_tensor(
                secondary_path, selected["line_no"]
            )

        filename_text = selected["filename"]
        filename_stem = Path(selected["filename"]).stem
        tag_1 = tags[0] if len(tags) >= 1 else ""
        tag_2 = tags[1] if len(tags) >= 2 else ""
        tags_text = tag_separator.join(tags) if tags else ""

        save_prefix, filename_body = self._build_save_prefix(
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
            tensor_secondary,
            filename_text,
            filename_stem,
            tag_1,
            tag_2,
            tags_text,
            save_prefix,
            filename_body,
            selected_index,
        )

    def _load_image_tensor(self, image_path, line_no):
        try:
            img = Image.open(image_path)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
        except Exception as e:
            raise ValueError(
                "Failed to open image at line {}: {} ({})".format(
                    line_no, image_path, e
                )
            )
        arr = np.array(img).astype(np.float32) / 255.0
        return torch.from_numpy(arr)[None,]

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

        parts = []
        for t in used_tags:
            parts.append(t)
        if action_text:
            parts.append(action_text)
        parts.append(datetime_str)

        safe_parts = []
        for p in parts:
            safe = _sanitize_filename_part(p)
            if safe != "":
                safe_parts.append(safe)

        filename_body = tag_separator.join(safe_parts)
        safe_date_folder = _sanitize_filename_part(date_folder)

        if safe_date_folder:
            save_prefix = "{}/{}".format(safe_date_folder, filename_body)
        else:
            save_prefix = filename_body
        return save_prefix, filename_body
