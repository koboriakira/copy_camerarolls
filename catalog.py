#!/usr/bin/env python3
"""
NAS 写真カタログ: 決定論メタデータ + LLM 解析キャッシュの永続レイヤー。

日付ディレクトリ（YYYY/MM/DD）ごとに `index.json`（正典） と `index.md`
（`index.json` から常に再生成される build artifact）を管理する。
osxphotos 由来の決定論メタデータを UUID キーで永続化し、PHOTO-3（vision LLM
解析）が書き込む `llm` ブロックのキャッシュ置き場にもなる。

ディレクトリ決定ロジックは backup.py の dest_dir_for() を単一のソースとして
再利用し、重複実装しない。

Usage:
    python3 catalog.py sync                 # バックアップ後に実行。upsert + index.md 再生成
    python3 catalog.py sync --limit 10
    python3 catalog.py rebuild               # 全再構築。既存の llm ブロックは UUID マージで温存
    python3 catalog.py render                # index.json から index.md のみ再生成
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from datetime import date as _date
from pathlib import Path

from backup import DEFAULT_DEST, dest_dir_for

try:
    import osxphotos
except ImportError:
    osxphotos = None

SCHEMA_VERSION = 1
CATALOG_FILENAME = "index.json"
MD_FILENAME = "index.md"

_UUID_RE = re.compile(
    r"^([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})(\..+)?$"
)
_VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v"}


def today_str() -> str:
    return _date.today().isoformat()


def default_llm_block() -> dict:
    return {
        "model": "",
        "prompt_version": "",
        "analyzed_at": "",
        "caption": "",
        "classification": "",
    }


def photo_type(photo) -> str:
    if getattr(photo, "screenshot", False):
        return "screenshot"
    if getattr(photo, "ismovie", False):
        return "video"
    return "photo"


def _type_from_extension(filename: str) -> str:
    """写真オブジェクトがない場合（rebuild でライブラリ外)のフォールバック推定。"""
    return "video" if Path(filename).suffix.lower() in _VIDEO_EXTENSIONS else "photo"


def _location_block(photo) -> dict | None:
    loc = getattr(photo, "location", None)
    if not loc:
        return None
    lat, lon = loc
    if lat is None or lon is None:
        return None
    return {"latitude": lat, "longitude": lon}


def _uuid_from_filename(name: str) -> str | None:
    m = _UUID_RE.match(name)
    return m.group(1).upper() if m else None


def build_record(
    photo,
    nas_filename: str,
    live_video_file: str | None,
    in_photos_library: bool = True,
) -> dict:
    """osxphotos の Photo オブジェクトから決定論メタデータのレコードを構築する。"""
    place = getattr(photo, "place", None)
    place_name = getattr(place, "name", None) if place else None
    date = getattr(photo, "date", None)

    return {
        "schema_version": SCHEMA_VERSION,
        "uuid": photo.uuid,
        "nas_filename": nas_filename,
        "original_filename": getattr(photo, "original_filename", None) or nas_filename,
        "date": date.isoformat() if date else None,
        "type": photo_type(photo),
        "live_video_file": live_video_file,
        "osxphotos": {
            "persons": list(getattr(photo, "persons", []) or []),
            "labels": list(getattr(photo, "labels", []) or []),
            "ai_caption": getattr(photo, "ai_caption", "") or "",
            "place": place_name or "",
            "location": _location_block(photo),
            "favorite": bool(getattr(photo, "favorite", False)),
            "albums": list(getattr(photo, "albums", []) or []),
            "refreshed_at": today_str(),
        },
        "llm": default_llm_block(),
        "in_photos_library": in_photos_library,
        "file_missing": False,
    }


def upsert_record(
    records: dict[str, dict], record: dict, source: dict[str, dict] | None = None
) -> dict[str, dict]:
    """record を records に upsert する。既存の llm ブロックは必ず温存する。

    source を指定すると、llm ブロックの継承元を records 自体ではなく source から
    探す（rebuild のように records を空から組み立て直す場合に使う）。
    """
    base = source if source is not None else records
    prior = base.get(record["uuid"])
    if prior and prior.get("llm"):
        record["llm"] = prior["llm"]
    records[record["uuid"]] = record
    return records


def atomic_write(path: Path, content: str) -> None:
    """tmp ファイル + rename でアトミックに書き込む（SMB 上の途中死対策）。"""
    tmp_path = path.parent / (path.name + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def load_catalog(dir_path: Path) -> dict[str, dict]:
    """dir_path の index.json を uuid キーの dict として読み込む。無ければ空 dict。"""
    path = dir_path / CATALOG_FILENAME
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_catalog(dir_path: Path, records: dict[str, dict]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / CATALOG_FILENAME
    content = json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write(path, content)


def mark_missing_files(dir_path: Path, records: dict[str, dict]) -> dict[str, dict]:
    """実ファイルが存在しないレコードに file_missing フラグを立てる（削除はしない）。"""
    for record in records.values():
        nas_path = dir_path / record["nas_filename"]
        record["file_missing"] = not nas_path.exists()
    return records


def _date_label(dir_path: Path) -> str:
    parts = dir_path.parts[-3:]
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return "-".join(parts)
    return dir_path.name


def render_index_md(dir_path: Path, records: dict[str, dict]) -> str:
    """index.json の内容から人間可読な index.md を生成する（手編集禁止の build artifact）。"""
    label = _date_label(dir_path)
    lines = [f"# {label}", "", f"{len(records)} 件"]

    if not records:
        lines.append("")
        lines.append("(写真なし)")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append(
        "| ファイル | 種別 | 元ファイル名 | 人物 | 場所 | GPS | お気に入り | Photos | 状態 | LLM |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    def sort_key(item):
        _uuid, record = item
        return record.get("date") or "", record.get("nas_filename", "")

    for _uuid, record in sorted(records.items(), key=sort_key):
        osx = record.get("osxphotos", {}) or {}
        llm = record.get("llm", {}) or {}
        persons = "、".join(osx.get("persons", [])) or "-"
        place = osx.get("place") or "-"
        loc = osx.get("location")
        gps = f"{loc['latitude']:.5f}, {loc['longitude']:.5f}" if loc else "-"
        favorite = "★" if osx.get("favorite") else ""
        in_lib = "○" if record.get("in_photos_library") else "×"
        status = "欠落" if record.get("file_missing") else ""
        classification = llm.get("classification") or ""
        caption = llm.get("caption") or osx.get("ai_caption") or ""
        if classification and caption:
            llm_col = f"{classification}: {caption}"
        else:
            llm_col = classification or caption or "-"

        lines.append(
            f"| {record.get('nas_filename', '')} "
            f"| {record.get('type', '')} "
            f"| {record.get('original_filename', '')} "
            f"| {persons} "
            f"| {place} "
            f"| {gps} "
            f"| {favorite} "
            f"| {in_lib} "
            f"| {status} "
            f"| {llm_col} |"
        )

    lines.append("")
    return "\n".join(lines) + "\n"


def write_index_md(dir_path: Path, records: dict[str, dict]) -> None:
    content = render_index_md(dir_path, records)
    atomic_write(dir_path / MD_FILENAME, content)


def iter_dated_dirs(dest: Path) -> list[Path]:
    """dest 配下の YYYY/MM/DD ディレクトリを列挙する（legacy 資産は対象外）。"""
    dirs: list[Path] = []
    if not dest.exists():
        return dirs
    for year_dir in sorted(dest.glob("[0-9][0-9][0-9][0-9]")):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.glob("[0-9][0-9]")):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.glob("[0-9][0-9]")):
                if day_dir.is_dir():
                    dirs.append(day_dir)
    return dirs


def sync(dest: Path, photos: Iterable) -> dict:
    """Photos ライブラリの photos を対象に、実ファイルが存在するものだけを upsert する。

    バックアップ実行直後に呼ぶ想定の軽量な増分更新。触れたディレクトリのみ
    index.json / index.md を再生成する。
    """
    touched: dict[Path, dict[str, dict]] = {}
    stats = {"upserted": 0, "skipped_missing_file": 0}

    for photo in photos:
        src = getattr(photo, "path", None)
        if not src:
            stats["skipped_missing_file"] += 1
            continue

        dir_path = dest_dir_for(dest, photo)
        nas_filename = Path(src).name
        nas_path = dir_path / nas_filename
        if not nas_path.exists():
            stats["skipped_missing_file"] += 1
            continue

        live_video_file = None
        live_src = getattr(photo, "path_live_photo", None)
        if getattr(photo, "live_photo", False) and live_src:
            live_candidate = dir_path / Path(live_src).name
            if live_candidate.exists():
                live_video_file = live_candidate.name

        record = build_record(photo, nas_filename, live_video_file, in_photos_library=True)

        if dir_path not in touched:
            touched[dir_path] = load_catalog(dir_path)
        upsert_record(touched[dir_path], record)
        stats["upserted"] += 1

    for dir_path, records in touched.items():
        mark_missing_files(dir_path, records)
        save_catalog(dir_path, records)
        write_index_md(dir_path, records)

    stats["directories"] = len(touched)
    return stats


def _fallback_record(
    uuid: str, nas_filename: str, live_video_file: str | None, prior: dict | None
) -> dict:
    """Photos ライブラリに現存しない uuid の代替レコードを組み立てる。

    既存カタログのレコードがあれば osxphotos ブロック・original_filename・
    date・llm を温存しつつ in_photos_library だけ false にする。既存データも
    なければファイル名から分かる範囲の最小レコードにする。
    """
    if prior:
        record = dict(prior)
        record["nas_filename"] = nas_filename
        record["live_video_file"] = live_video_file
        record["in_photos_library"] = False
        return record

    return {
        "schema_version": SCHEMA_VERSION,
        "uuid": uuid,
        "nas_filename": nas_filename,
        "original_filename": nas_filename,
        "date": None,
        "type": _type_from_extension(nas_filename),
        "live_video_file": live_video_file,
        "osxphotos": {
            "persons": [],
            "labels": [],
            "ai_caption": "",
            "place": "",
            "location": None,
            "favorite": False,
            "albums": [],
            "refreshed_at": today_str(),
        },
        "llm": default_llm_block(),
        "in_photos_library": False,
        "file_missing": False,
    }


def rebuild(dest: Path, photos: Iterable) -> dict:
    """NAS 上の全 YYYY/MM/DD ディレクトリを実ファイルから走査して全再構築する。

    現在の Photos ライブラリに存在する uuid は osxphotos メタデータで更新し、
    存在しない uuid は in_photos_library=false として既存データを温存する。
    ディスクから消えたレコードは削除せず file_missing フラグを立てる。
    既存の llm ブロックは常に UUID マージで温存する。
    """
    photos_by_uuid = {photo.uuid.upper(): photo for photo in photos}
    stats = {"directories": 0, "records": 0, "in_library": 0, "not_in_library": 0}

    for dir_path in iter_dated_dirs(dest):
        existing = load_catalog(dir_path)
        records: dict[str, dict] = {}

        by_uuid: dict[str, list[Path]] = {}
        for file_path in sorted(dir_path.iterdir()):
            if not file_path.is_file():
                continue
            uuid = _uuid_from_filename(file_path.name)
            if uuid is None:
                continue
            by_uuid.setdefault(uuid, []).append(file_path)

        for uuid, files in by_uuid.items():
            primary = None
            live_video = None
            if len(files) > 1:
                for f in files:
                    if f.suffix.lower() in _VIDEO_EXTENSIONS:
                        live_video = f
                    else:
                        primary = f
            if primary is None:
                primary = files[0]

            photo = photos_by_uuid.get(uuid)
            if photo is not None:
                record = build_record(
                    photo,
                    primary.name,
                    live_video.name if live_video else None,
                    in_photos_library=True,
                )
                stats["in_library"] += 1
            else:
                record = _fallback_record(
                    uuid,
                    primary.name,
                    live_video.name if live_video else None,
                    existing.get(uuid),
                )
                stats["not_in_library"] += 1

            upsert_record(records, record, source=existing)

        # ディスクから消えたが index.json に残っていたレコードは削除せずフラグ付けする
        for uuid, prior_record in existing.items():
            if uuid not in records:
                carried = dict(prior_record)
                carried["file_missing"] = True
                records[uuid] = carried

        save_catalog(dir_path, records)
        write_index_md(dir_path, records)
        stats["directories"] += 1
        stats["records"] += len(records)

    return stats


def render(dest: Path, dirs: Iterable[Path] | None = None) -> dict:
    """index.json から index.md だけを再生成する（Photos ライブラリには触れない）。"""
    target_dirs = list(dirs) if dirs is not None else iter_dated_dirs(dest)
    stats = {"rendered": 0}
    for dir_path in target_dirs:
        records = load_catalog(dir_path)
        write_index_md(dir_path, records)
        stats["rendered"] += 1
    return stats


def update_llm_block(dir_path: Path, uuid: str, llm_data: dict) -> dict:
    """PHOTO-3 用のフック: 1 レコードの llm ブロックを更新し index.md を再生成する。

    キャッシュ無効化キーは (uuid, model, prompt_version)。呼び出し側で
    prompt_version を上げたときのみ再解析することを想定。
    """
    records = load_catalog(dir_path)
    if uuid not in records:
        raise KeyError(f"uuid {uuid} not found in {dir_path / CATALOG_FILENAME}")

    records[uuid]["llm"] = {**default_llm_block(), **records[uuid].get("llm", {}), **llm_data}
    save_catalog(dir_path, records)
    write_index_md(dir_path, records)
    return records[uuid]


def build_parser() -> argparse.ArgumentParser:
    """CLI パーサーを構築する（テストで parse_args() を直接検証できるよう分離）。

    --dest は各サブコマンドの後ろに指定する（`catalog.py sync --dest X`）。
    トップレベルパーサーにも同名オプションを重複定義すると、サブパーサー側の
    デフォルト値が共有 namespace を上書きしてしまう argparse の既知の罠がある
    ため、--dest は各サブパーサーにのみ定義する。
    """
    dest_parser = argparse.ArgumentParser(add_help=False)
    dest_parser.add_argument("--dest", default=DEFAULT_DEST)

    parser = argparse.ArgumentParser(description="NAS 写真カタログ管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser(
        "sync", parents=[dest_parser], help="バックアップ後に実行。upsert + index.md 再生成"
    )
    sync_parser.add_argument("--limit", type=int, help="処理する写真数を制限（テスト用）")

    sub.add_parser(
        "rebuild", parents=[dest_parser], help="全再構築。既存の llm ブロックは UUID マージで温存"
    )
    sub.add_parser(
        "render", parents=[dest_parser], help="index.md のみ再生成（Photos ライブラリには触れない）"
    )

    return parser


def main():
    args = build_parser().parse_args()

    dest = Path(args.dest)
    if not dest.exists():
        print(f"Error: {dest} が見つかりません。NAS はマウントされていますか？", file=sys.stderr)
        sys.exit(1)

    if args.command == "render":
        stats = render(dest)
        print(f"index.md 再生成: {stats['rendered']} ディレクトリ")
        return

    if osxphotos is None:
        print("osxphotos が必要です: pip install osxphotos", file=sys.stderr)
        sys.exit(1)

    print("Photos ライブラリを読み込み中...")
    db = osxphotos.PhotosDB()
    all_photos = db.photos()
    print(f"ライブラリ: {len(all_photos)} 枚")

    if args.command == "sync":
        limit = getattr(args, "limit", None)
        photos = all_photos[:limit] if limit else all_photos
        stats = sync(dest, photos)
        print(f"upsert: {stats['upserted']} 件 / {stats['directories']} ディレクトリ")
        print(f"スキップ (未バックアップ): {stats['skipped_missing_file']} 件")
    elif args.command == "rebuild":
        stats = rebuild(dest, all_photos)
        print(f"再構築: {stats['directories']} ディレクトリ / {stats['records']} レコード")
        print(f"  Photos ライブラリ内: {stats['in_library']} / ライブラリ外: {stats['not_in_library']}")


if __name__ == "__main__":
    main()
