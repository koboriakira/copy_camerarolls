#!/usr/bin/env python3
"""
写真 facts の決定論抽出（daily facts 統合）。

osxphotos への直接アクセスは行わない。PHOTO-4 のカタログ（catalog.py が管理する
日付ディレクトリ単位の `index.json`）を読み取り元とする「ビュー」として、
daily facts ドキュメントに「## 写真」セクションを書き込む／再生成する。

抽出ロジック（persons / labels / ai_caption / location 等の取得）は catalog.py が
既に担っているため、本モジュールでは重複実装しない。ここでの責務は
(1) 日付から catalog レコードを読み込む (2) 三値分類の決定論ルールを適用して
集計する (3) daily facts の Markdown セクションとして書き出す、の3点のみ。

Usage:
    python3 daily_facts.py 2026-03-01 --dest /Volumes/photo --out-dir ./facts
    python3 daily_facts.py 2026-03-01 --dest /Volumes/photo --out-dir ./facts --dry-run
    python3 daily_facts.py 2026-03-01 --dest /Volumes/photo --out-dir ./facts \\
        --family 太郎,花子 --data-labels food,receipt --memory-locations "しながわ水族館"

`--out-dir` に既定値は無い。daily facts の置き場所（Obsidian Vault の
`Log/daily/` 等）は利用者が明示的に指定すること。
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from datetime import date as _date
from pathlib import Path

from backup import DEFAULT_DEST
from catalog import atomic_write, load_catalog

HEADING = "## 写真"

# osxphotos の Apple ML ラベルは基本的に英語表記のため、既定のキーワードは英語で
# 持つ。日本語ラベルを使う環境では --data-labels で上書きする。
DEFAULT_DATA_LABEL_KEYWORDS = frozenset({"food", "receipt", "document", "recipe"})

SCREENSHOT = "screenshot"
VIDEO = "video"
DATA_CANDIDATE = "data_candidate"
MEMORY_CANDIDATE = "memory_candidate"
UNCLASSIFIED = "unclassified"


def day_dir(dest: Path, day: _date) -> Path:
    """catalog.py / backup.py の dest_dir_for と同じ規則で日付ディレクトリを組み立てる。"""
    return dest / f"{day.year}" / f"{day.month:02d}" / f"{day.day:02d}"


def load_day_records(dest: Path, day: _date) -> dict[str, dict]:
    """指定日の index.json を読み込む。ディレクトリ／ファイルが無ければ空 dict。"""
    return load_catalog(day_dir(dest, day))


def classify_record(
    record: dict,
    *,
    family_names: Iterable[str] = (),
    data_labels: Iterable[str] = DEFAULT_DATA_LABEL_KEYWORDS,
    memory_locations: Iterable[str] = (),
) -> str:
    """三値分類の決定論ルール（Phase 3 の前置フィルタ）。

    優先順位（issue #2 の記載順 + issue #8 で video を追加）:
      1. screenshot → screenshot（データ写真 or ノイズ。三値分類の対象外）
      1.5. video（type == "video"、ismovie=True の独立動画）→ video
           （issue #8: 動画は LLM 解析対象外のため三値分類の対象外。
           Live Photo companion 動画は親レコードの type を引き継がず
           "photo" のままなのでここには来ない）
      2. labels が data_labels と交差 → data_candidate
      3. persons が family_names と交差、または favorite、または
         place が memory_locations に含まれる → memory_candidate
      4. いずれにも該当しない → unclassified（Phase 3 の LLM 判定対象）
    """
    if record.get("type") == SCREENSHOT:
        return SCREENSHOT

    if record.get("type") == VIDEO:
        return VIDEO

    osx = record.get("osxphotos") or {}

    labels = {str(label).lower() for label in (osx.get("labels") or [])}
    data_keywords = {str(kw).lower() for kw in data_labels}
    if labels & data_keywords:
        return DATA_CANDIDATE

    persons = set(osx.get("persons") or [])
    if persons & set(family_names):
        return MEMORY_CANDIDATE

    if osx.get("favorite"):
        return MEMORY_CANDIDATE

    place = osx.get("place") or ""
    if place and place in set(memory_locations):
        return MEMORY_CANDIDATE

    return UNCLASSIFIED


def summarize_records(
    records: dict[str, dict],
    *,
    family_names: Iterable[str] = (),
    data_labels: Iterable[str] = DEFAULT_DATA_LABEL_KEYWORDS,
    memory_locations: Iterable[str] = (),
) -> dict:
    """catalog レコード群を daily facts 用に集計する。"""
    place_counts: Counter[str] = Counter()
    person_counts: Counter[str] = Counter()
    screenshot_count = 0
    video_count = 0
    memory_count = 0
    data_count = 0
    unclassified: list[dict] = []

    for uuid, record in records.items():
        osx = record.get("osxphotos") or {}

        place = osx.get("place") or ""
        if place:
            place_counts[place] += 1
        for person in osx.get("persons") or []:
            person_counts[person] += 1

        category = classify_record(
            record,
            family_names=family_names,
            data_labels=data_labels,
            memory_locations=memory_locations,
        )
        if category == SCREENSHOT:
            screenshot_count += 1
        elif category == VIDEO:
            video_count += 1
        elif category == MEMORY_CANDIDATE:
            memory_count += 1
        elif category == DATA_CANDIDATE:
            data_count += 1
        else:
            unclassified.append(
                {
                    "uuid": uuid,
                    "nas_filename": record.get("nas_filename", ""),
                    "original_filename": record.get("original_filename", ""),
                }
            )

    total = len(records)
    return {
        "total": total,
        "screenshot_count": screenshot_count,
        "non_screenshot_count": total - screenshot_count,
        "video_count": video_count,
        "place_counts": place_counts,
        "person_counts": person_counts,
        "memory_count": memory_count,
        "data_count": data_count,
        "unclassified": unclassified,
    }


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "(なし)"
    return ", ".join(f"{name}({n}枚)" for name, n in counts.most_common())


def render_photo_section(
    records: dict[str, dict],
    *,
    family_names: Iterable[str] = (),
    data_labels: Iterable[str] = DEFAULT_DATA_LABEL_KEYWORDS,
    memory_locations: Iterable[str] = (),
) -> str:
    """daily facts に埋め込む「## 写真」セクションの Markdown を生成する。"""
    summary = summarize_records(
        records,
        family_names=family_names,
        data_labels=data_labels,
        memory_locations=memory_locations,
    )

    lines = [
        HEADING,
        "",
        f"- 撮影: {summary['total']}枚（スクショ除外後 {summary['non_screenshot_count']}枚）",
        f"- 場所: {_format_counts(summary['place_counts'])}",
        f"- 人物: {_format_counts(summary['person_counts'])}",
        f"- 動画: {summary['video_count']}本（LLM解析対象外）",
        f"- 思い出候補: {summary['memory_count']}枚（人物+場所+お気に入り）",
        f"- データ写真候補: {summary['data_count']}枚（食べ物ラベル）",
        f"- 未分類: {len(summary['unclassified'])}枚（Phase 3 対象）",
    ]
    for item in summary["unclassified"]:
        name = item["original_filename"] or item["nas_filename"]
        lines.append(f"  - {name}")

    return "\n".join(lines) + "\n"


def _split_sections(content: str) -> tuple[list[str], dict[str, list[str]]]:
    """Markdown を (見出し無し前文, {見出し: 本文行}) に分解する。

    dict は挿入順を保つため、既存セクションの並び順はそのまま温存される。
    """
    lines = content.splitlines()
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in lines:
        if line.startswith("## "):
            current = line.rstrip()
            sections.setdefault(current, [])
            continue
        if current is None:
            preamble.append(line)
        else:
            sections[current].append(line)

    return preamble, sections


def _join_sections(preamble: list[str], sections: dict[str, list[str]]) -> str:
    parts: list[str] = []

    pre_text = "\n".join(preamble).rstrip("\n")
    if pre_text:
        parts.append(pre_text)

    for heading, body in sections.items():
        body_text = "\n".join(body).strip("\n")
        block = heading if not body_text else f"{heading}\n{body_text}"
        parts.append(block)

    return "\n\n".join(parts).rstrip("\n") + "\n"


def upsert_section(path: Path, section_markdown: str, heading: str = HEADING) -> str:
    """daily facts ファイルの heading セクションだけを書き換える（他のセクションは温存）。

    ファイルが存在しない場合は新規作成する。書き込みは atomic_write を再利用する。
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    preamble, sections = _split_sections(existing)

    body_lines = section_markdown.splitlines()
    if body_lines and body_lines[0].strip() == heading:
        body_lines = body_lines[1:]
    while body_lines and body_lines[0] == "":
        body_lines.pop(0)

    sections[heading] = body_lines

    new_content = _join_sections(preamble, sections)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, new_content)
    return new_content


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="写真 facts を決定論抽出し daily facts の「## 写真」セクションに統合する"
    )
    parser.add_argument("date", help="対象日 (YYYY-MM-DD)")
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST,
        help="NAS カタログのルート（catalog.py の --dest と同じ場所を指定する）",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help=(
            "daily facts の出力先ディレクトリ（例: Obsidian Vault の Log/daily/）。"
            "本ツールはこのパスに既定値を持たない。<date>.md を読み書きする"
        ),
    )
    parser.add_argument(
        "--family",
        default="",
        help="思い出候補と判定する人物名（osxphotos の persons 表示名）をカンマ区切りで指定",
    )
    parser.add_argument(
        "--data-labels",
        default=",".join(sorted(DEFAULT_DATA_LABEL_KEYWORDS)),
        help="データ写真候補と判定する osxphotos labels のキーワード（カンマ区切り、大小文字無視）",
    )
    parser.add_argument(
        "--memory-locations",
        default="",
        help="思い出候補と判定する place 名（カンマ区切り、完全一致）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="書き込まずセクションを標準出力に表示する"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    day = _date.fromisoformat(args.date)

    records = load_day_records(Path(args.dest), day)
    section = render_photo_section(
        records,
        family_names=_split_csv(args.family),
        data_labels=_split_csv(args.data_labels) or DEFAULT_DATA_LABEL_KEYWORDS,
        memory_locations=_split_csv(args.memory_locations),
    )

    if args.dry_run:
        print(section)
        return

    out_path = Path(args.out_dir) / f"{args.date}.md"
    upsert_section(out_path, section)
    print(f"更新: {out_path}")


if __name__ == "__main__":
    main()
