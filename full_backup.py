#!/usr/bin/env python3
"""
iCloud Photos → NAS → S3 full backup pipeline.

1. Scan Photos library for new (unsynced) photos
2. Show count and ask for confirmation
3. Copy to NAS
4. Sync NAS to S3 (Glacier Deep Archive)

Usage:
    python3 full_backup.py              # interactive (confirmation prompt)
    python3 full_backup.py --yes        # skip confirmation
    python3 full_backup.py --dry-run    # plan only, no copy/sync
"""

import argparse
import json
import subprocess
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


def count_new_photos(dest: Path) -> tuple[int, int, int]:
    """Return (new_local, icloud_only, total) counts."""
    state_path = dest / STATE_FILENAME
    copied = load_state(state_path)

    db = osxphotos.PhotosDB()
    all_photos = db.photos()

    new_local = 0
    icloud_only = 0

    for photo in all_photos:
        if photo.uuid in copied:
            continue
        if photo.path and Path(photo.path).exists():
            new_local += 1
        else:
            icloud_only += 1

    return new_local, icloud_only, len(all_photos)


def run_nas_backup(dest: str, dry_run: bool) -> int:
    cmd = [sys.executable, "backup.py", "--dest", dest]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd)


def run_s3_sync(source: str, dry_run: bool) -> int:
    cmd = [sys.executable, "s3_sync.py", "--source", source]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(description="iCloud Photos → NAS → S3 full backup")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="NAS mount path")
    parser.add_argument("--dry-run", action="store_true", help="plan only, no copy/sync")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    args = parser.parse_args()

    dest = Path(args.dest)
    if not dest.exists():
        print(f"Error: {dest} が見つかりません。NAS はマウントされていますか？", file=sys.stderr)
        sys.exit(1)

    print("=" * 50)
    print("Photos ライブラリをスキャン中...")
    print("=" * 50)
    new_local, icloud_only, total = count_new_photos(dest)

    print(f"\nライブラリ全体: {total} 枚")
    print(f"新規（ローカルあり）: {new_local} 枚 ← バックアップ対象")
    if icloud_only > 0:
        print(f"新規（iCloudのみ）: {icloud_only} 枚（ローカル未ダウンロードのためスキップ）")

    if new_local == 0:
        print("\n新規の写真はありません。")
        print("\nNAS → S3 同期のみ実行します...")
        rc = run_s3_sync(args.dest, args.dry_run)
        sys.exit(rc)

    if not args.yes and not args.dry_run:
        answer = input(f"\n{new_local} 枚の写真を NAS にバックアップし、S3 に同期します。よろしいですか？ [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("中断しました。")
            sys.exit(0)

    print("\n" + "=" * 50)
    print("Step 1/2: iCloud Photos → NAS")
    print("=" * 50)
    rc = run_nas_backup(args.dest, args.dry_run)
    if rc != 0:
        print(f"\nNAS バックアップが異常終了しました (exit code: {rc})", file=sys.stderr)
        sys.exit(rc)

    print("\n" + "=" * 50)
    print("Step 2/2: NAS → S3 (Glacier Deep Archive)")
    print("=" * 50)
    rc = run_s3_sync(args.dest, args.dry_run)
    if rc != 0:
        print(f"\nS3 同期が異常終了しました (exit code: {rc})", file=sys.stderr)
        sys.exit(rc)

    print("\n" + "=" * 50)
    print("全行程完了")
    print("=" * 50)


if __name__ == "__main__":
    main()
