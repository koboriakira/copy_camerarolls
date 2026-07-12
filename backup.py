#!/usr/bin/env python3
"""
Apple Photos → NAS incremental backup.

Reads the macOS Photos library via osxphotos, copies originals to NAS
in YYYY/MM/DD directory structure. Tracks copied UUIDs for incremental runs.

Usage:
    python3 backup.py                    # default: /Volumes/photo
    python3 backup.py --dest /path/to/nas
    python3 backup.py --dry-run
    python3 backup.py --limit 10         # test with 10 photos
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    import osxphotos
except ImportError:
    print("osxphotos が必要です: pip install osxphotos", file=sys.stderr)
    sys.exit(1)

DEFAULT_DEST = "/Volumes/photo"
STATE_FILENAME = ".backup_state.json"


def load_state(path: Path) -> set[str]:
    if path.exists():
        with open(path) as f:
            return set(json.load(f).get("copied_uuids", []))
    return set()


def save_state(path: Path, uuids: set[str]) -> None:
    with open(path, "w") as f:
        json.dump({"copied_uuids": sorted(uuids)}, f)


def dest_dir_for(base: Path, photo) -> Path:
    d = photo.date
    return base / f"{d.year}" / f"{d.month:02d}" / f"{d.day:02d}"


def copy_one(photo, dest_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Copy photo (+ Live Photo video) to dest_dir.
    Returns (files_copied, live_videos_copied)."""
    src = photo.path
    if not src or not Path(src).exists():
        return 0, 0

    dest_dir.mkdir(parents=True, exist_ok=True)
    files, live = 0, 0

    dest_file = dest_dir / Path(src).name
    if dest_file.exists():
        files += 1
    elif dry_run:
        print(f"  [DRY] {Path(src).name} → {dest_dir.relative_to(dest_dir.parents[3])}")
        files += 1
    else:
        shutil.copy2(src, dest_file)
        files += 1

    if photo.live_photo and photo.path_live_photo:
        live_src = Path(photo.path_live_photo)
        if live_src.exists():
            live_dest = dest_dir / live_src.name
            if not live_dest.exists():
                if not dry_run:
                    shutil.copy2(str(live_src), live_dest)
                live += 1

    return files, live


def main():
    parser = argparse.ArgumentParser(description="Apple Photos → NAS incremental backup")
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true", help="計画だけ表示、コピーしない")
    parser.add_argument("--limit", type=int, help="処理する写真数を制限（テスト用）")
    parser.add_argument("--reset-state", action="store_true", help="前回の状態を無視して全件処理")
    args = parser.parse_args()

    dest = Path(args.dest)
    if not dest.exists():
        print(f"Error: {dest} が見つかりません。NAS はマウントされていますか？", file=sys.stderr)
        sys.exit(1)

    state_path = dest / STATE_FILENAME
    copied = set() if args.reset_state else load_state(state_path)
    print(f"既知の UUID: {len(copied)} 件")

    print("Photos ライブラリを読み込み中...")
    db = osxphotos.PhotosDB()
    all_photos = db.photos()
    print(f"ライブラリ: {len(all_photos)} 枚")

    photos = all_photos[:args.limit] if args.limit else all_photos

    new_uuids: set[str] = set()
    stats = {"copied": 0, "skipped_known": 0, "skipped_icloud": 0, "errors": 0, "live": 0}

    for i, photo in enumerate(photos, 1):
        if photo.uuid in copied:
            stats["skipped_known"] += 1
            continue

        try:
            files, live = copy_one(photo, dest_dir_for(dest, photo), args.dry_run)
            if files > 0:
                stats["copied"] += files
                stats["live"] += live
                new_uuids.add(photo.uuid)
            else:
                stats["skipped_icloud"] += 1
        except Exception as e:
            print(f"Error [{photo.original_filename}]: {e}", file=sys.stderr)
            stats["errors"] += 1

        if i % 500 == 0:
            print(f"  進捗: {i}/{len(photos)}")
            if not args.dry_run and new_uuids:
                save_state(state_path, copied | new_uuids)

    if not args.dry_run and new_uuids:
        save_state(state_path, copied | new_uuids)

    tag = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{tag}バックアップ完了:")
    print(f"  コピー:       {stats['copied']}")
    print(f"  Live Photo:   {stats['live']}")
    print(f"  既知 (skip):  {stats['skipped_known']}")
    print(f"  iCloud のみ:  {stats['skipped_icloud']}")
    print(f"  エラー:       {stats['errors']}")
    print(f"  ライブラリ全体: {len(all_photos)}")

    if stats["skipped_icloud"] > 0:
        print(
            f"\n注意: {stats['skipped_icloud']} 件は iCloud のみでローカル未ダウンロードのためスキップしました。",
            file=sys.stderr,
        )
        print(
            "Photos.app で個別にダウンロードすれば、次回実行時に自動的にバックアップされます。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
