#!/usr/bin/env python3
"""
NAS転送検証済み写真・動画の削除候補一覧（削除は一切自動化しない）。

Photos ライブラリ（osxphotos、読み取り専用）と NAS の `.backup_state.json`
（backup.py が書く状態ファイル）を突き合わせ、以下をすべて満たすものだけを
「安全に削除可能」な候補として一覧表示する。

    1. ローカルにダウンロード済み（photo.path が実在する）
    2. NAS の状態ファイルに UUID が記録されている（backup.py が転送済みと記録）
    3. 実際に NAS 上にファイルが存在し、ローカルとファイルサイズが一致する
       （状態ファイルだけを信用せず、実ファイルで再検証する）

条件1・2を満たすが条件3を満たさないもの（NAS側欠損・サイズ不一致）は、
「安全リスト」とは明確に区別した「警告」セクションに出す。状態ファイルの破損や
NAS側の欠損があっても、それを誤って安全と報告しないことが本スクリプトの
最重要な安全要件である。

**重要: 削除は一切行わない。** Photos ライブラリへの書き込み・削除、
AppleScript による Photos.app 操作、NAS への書き込みは一切行わない
（すべて読み取り専用アクセス）。実際の削除（ローカルダウンロードのみ取り消すか、
iCloud含め完全削除するか）は Photos.app 上でユーザー自身が手動で行うこと。

Usage:
    python3 offload_candidates.py                    # 既定: /Volumes/photo
    python3 offload_candidates.py --dest /path/to/nas
    python3 offload_candidates.py --type video        # 動画のみに絞る
    python3 offload_candidates.py --limit 10          # テスト用
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import osxphotos
except ImportError:
    print("osxphotos が必要です: pip install osxphotos", file=sys.stderr)
    sys.exit(1)

from backup import DEFAULT_DEST, STATE_FILENAME, dest_dir_for, load_state
from catalog import photo_type

SAFE = "safe"
SIZE_MISMATCH = "size_mismatch"
MISSING_ON_NAS = "missing_on_nas"


def nas_path_for(dest: Path, photo) -> Path:
    """photo に対応する NAS 上のパスを返す（backup.py の copy_one と同じ規則）。"""
    return dest_dir_for(dest, photo) / Path(photo.path).name


def evaluate_candidate(photo, dest: Path, backed_up_uuids: set[str]) -> dict | None:
    """1枚の photo を判定する。判定対象外（ローカル未DL・未バックアップ記録）なら None。

    戻り値の dict のキー: uuid, type, date, local_path, nas_path,
    local_size, nas_size, status。status は SAFE / SIZE_MISMATCH / MISSING_ON_NAS。
    """
    src = photo.path
    if not src or not Path(src).exists():
        return None  # ローカル未ダウンロード（iCloudのみ）→ 削除候補になり得ない

    if photo.uuid not in backed_up_uuids:
        return None  # 状態ファイル未記録（backup.py 未実行・未転送）→ 対象外

    local_path = Path(src)
    local_size = local_path.stat().st_size
    nas_path = nas_path_for(dest, photo)

    if not nas_path.exists():
        nas_size = None
        status = MISSING_ON_NAS
    else:
        nas_size = nas_path.stat().st_size
        status = SAFE if nas_size == local_size else SIZE_MISMATCH

    return {
        "uuid": photo.uuid,
        "type": photo_type(photo),
        "date": photo.date,
        "local_path": local_path,
        "nas_path": nas_path,
        "local_size": local_size,
        "nas_size": nas_size,
        "status": status,
    }


def collect_candidates(
    photos, dest: Path, backed_up_uuids: set[str], type_filter: str | None = None
) -> list[dict]:
    """写真リストを評価し、判定対象のレコード（安全・警告いずれも）を返す。"""
    records = []
    for photo in photos:
        record = evaluate_candidate(photo, dest, backed_up_uuids)
        if record is None:
            continue
        if type_filter and record["type"] != type_filter:
            continue
        records.append(record)
    return records


def format_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def render_report(records: list[dict]) -> str:
    """安全リストと警告リストを分けたレポートを Markdown 風テキストで返す。"""
    safe = sorted(
        (r for r in records if r["status"] == SAFE),
        key=lambda r: r["local_size"],
        reverse=True,
    )
    warnings = [r for r in records if r["status"] != SAFE]
    total_size = sum(r["local_size"] for r in safe)

    lines = [f"## 削除候補（NAS転送検証済み・{len(safe)}件、合計 {format_size(total_size)}）", ""]
    if not safe:
        lines.append("(該当なし)")
    for r in safe:
        lines.append(
            f"- [{r['type']}] {format_size(r['local_size'])}\t"
            f"{r['date'].date().isoformat()}\t{r['local_path']} ⇔ {r['nas_path']}"
        )

    lines.append("")
    lines.append(f"## 警告: 検証できなかったファイル（{len(warnings)}件）")
    lines.append("")
    if not warnings:
        lines.append("(なし)")
    for r in warnings:
        if r["status"] == MISSING_ON_NAS:
            reason = f"NAS側に見つかりません（{r['nas_path']}）"
        else:
            reason = (
                f"サイズ不一致（ローカル {format_size(r['local_size'])} / "
                f"NAS {format_size(r['nas_size'])}）"
            )
        lines.append(f"- [{r['type']}] {r['date'].date().isoformat()}\t{r['local_path']} — {reason}")

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "NAS転送検証済みでローカル削除しても安全な写真・動画を一覧表示する"
            "（削除は一切行わない。Photos.app 上で手動削除すること）"
        )
    )
    parser.add_argument("--dest", default=DEFAULT_DEST, help="NAS のバックアップ先ルート（読み取り専用アクセス）")
    parser.add_argument("--type", choices=["photo", "video", "screenshot"], help="種別で絞り込む")
    parser.add_argument("--limit", type=int, help="処理する写真数を制限（テスト用）")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    dest = Path(args.dest)
    if not dest.exists():
        print(f"Error: {dest} が見つかりません。NAS はマウントされていますか？", file=sys.stderr)
        sys.exit(1)

    backed_up_uuids = load_state(dest / STATE_FILENAME)
    print(f"NAS 状態ファイルに記録済みの UUID: {len(backed_up_uuids)} 件")

    print("Photos ライブラリを読み込み中...")
    db = osxphotos.PhotosDB()
    all_photos = db.photos()
    photos = all_photos[: args.limit] if args.limit else all_photos
    print(f"ライブラリ: {len(all_photos)} 枚")

    records = collect_candidates(photos, dest, backed_up_uuids, type_filter=args.type)
    print()
    print(render_report(records))


if __name__ == "__main__":
    main()
