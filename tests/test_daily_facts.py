from datetime import date

import backup
from catalog import save_catalog
from daily_facts import (
    DATA_CANDIDATE,
    DEFAULT_DATA_LABEL_KEYWORDS,
    MEMORY_CANDIDATE,
    SCREENSHOT,
    UNCLASSIFIED,
    VIDEO,
    build_parser,
    classify_record,
    day_dir,
    load_day_records,
    render_photo_section,
    summarize_records,
    upsert_section,
)


def make_record(
    uuid="UUID-1",
    nas_filename="a.jpg",
    original_filename="IMG_1.HEIC",
    record_type="photo",
    persons=None,
    labels=None,
    place="",
    favorite=False,
):
    return {
        "uuid": uuid,
        "nas_filename": nas_filename,
        "original_filename": original_filename,
        "type": record_type,
        "osxphotos": {
            "persons": persons or [],
            "labels": labels or [],
            "place": place,
            "favorite": favorite,
        },
    }


# --- day_dir -----------------------------------------------------------------


def test_day_dir_builds_year_month_day_path(tmp_path):
    assert day_dir(tmp_path, date(2026, 3, 1)) == tmp_path / "2026" / "03" / "01"


def test_day_dir_matches_backup_dest_dir_for(tmp_path):
    from datetime import datetime
    from types import SimpleNamespace

    photo = SimpleNamespace(date=datetime(2026, 7, 9, 8, 0, 0))
    assert day_dir(tmp_path, photo.date.date()) == backup.dest_dir_for(tmp_path, photo)


# --- load_day_records ----------------------------------------------------------


def test_load_day_records_missing_dir_returns_empty(tmp_path):
    assert load_day_records(tmp_path, date(2026, 3, 1)) == {}


def test_load_day_records_reads_existing_catalog(tmp_path):
    dir_path = tmp_path / "2026" / "03" / "01"
    records = {"UUID-1": make_record()}
    save_catalog(dir_path, records)

    assert load_day_records(tmp_path, date(2026, 3, 1)) == records


# --- classify_record -----------------------------------------------------------


def test_classify_screenshot():
    record = make_record(record_type="screenshot", favorite=True)
    assert classify_record(record) == SCREENSHOT


def test_classify_data_candidate_by_label():
    record = make_record(labels=["Food"])
    assert (
        classify_record(record, data_labels=DEFAULT_DATA_LABEL_KEYWORDS) == DATA_CANDIDATE
    )


def test_classify_data_candidate_label_match_is_case_insensitive():
    record = make_record(labels=["RECEIPT"])
    assert classify_record(record, data_labels=["receipt"]) == DATA_CANDIDATE


def test_classify_memory_candidate_by_family_person():
    record = make_record(persons=["太郎"])
    assert classify_record(record, family_names=["太郎", "花子"]) == MEMORY_CANDIDATE


def test_classify_memory_candidate_by_favorite():
    record = make_record(favorite=True)
    assert classify_record(record) == MEMORY_CANDIDATE


def test_classify_memory_candidate_by_location():
    record = make_record(place="しながわ水族館")
    assert (
        classify_record(record, memory_locations=["しながわ水族館"]) == MEMORY_CANDIDATE
    )


def test_classify_unclassified_when_no_rule_matches():
    record = make_record(place="自宅")
    assert classify_record(record) == UNCLASSIFIED


def test_classify_screenshot_takes_priority_over_other_rules():
    record = make_record(record_type="screenshot", favorite=True, labels=["Food"])
    assert classify_record(record, data_labels=["food"]) == SCREENSHOT


def test_classify_video():
    record = make_record(record_type="video")
    assert classify_record(record) == VIDEO


def test_classify_video_takes_priority_over_other_rules():
    record = make_record(
        record_type="video", favorite=True, labels=["Food"], persons=["太郎"]
    )
    assert (
        classify_record(record, family_names=["太郎"], data_labels=["food"]) == VIDEO
    )


def test_classify_data_label_takes_priority_over_memory_rules():
    record = make_record(labels=["Food"], favorite=True)
    assert classify_record(record, data_labels=["food"]) == DATA_CANDIDATE


# --- summarize_records / render_photo_section (golden example from issue) ------


def _build_issue_example_records():
    records = {}

    for i in range(8):
        records[f"SS-{i}"] = make_record(uuid=f"SS-{i}", nas_filename=f"ss{i}.png", record_type="screenshot")

    for i in range(3):
        records[f"DATA-{i}"] = make_record(
            uuid=f"DATA-{i}",
            nas_filename=f"data{i}.jpg",
            place="自宅",
            labels=["レシート"],
        )

    for i in range(6):
        records[f"MEM-TARO-{i}"] = make_record(
            uuid=f"MEM-TARO-{i}",
            nas_filename=f"taro{i}.jpg",
            place="しながわ水族館",
            persons=["太郎"],
        )
    for i in range(2):
        records[f"MEM-HANAKO-{i}"] = make_record(
            uuid=f"MEM-HANAKO-{i}",
            nas_filename=f"hanako{i}.jpg",
            place="しながわ水族館",
            persons=["花子"],
        )

    for i in range(2):
        records[f"UNC-HANAKO-{i}"] = make_record(
            uuid=f"UNC-HANAKO-{i}",
            nas_filename=f"unc-hanako{i}.jpg",
            place="自宅",
            persons=["花子"],
        )
    for i in range(2):
        records[f"UNC-{i}"] = make_record(
            uuid=f"UNC-{i}",
            nas_filename=f"unc{i}.jpg",
            original_filename=f"unc{i}.jpg",
            place="自宅",
        )

    return records


def test_summarize_records_matches_issue_example_counts():
    records = _build_issue_example_records()

    summary = summarize_records(
        records,
        data_labels=["レシート"],
        memory_locations=["しながわ水族館"],
    )

    assert summary["total"] == 23
    assert summary["screenshot_count"] == 8
    assert summary["non_screenshot_count"] == 15
    assert summary["memory_count"] == 8
    assert summary["data_count"] == 3
    assert len(summary["unclassified"]) == 4
    assert summary["place_counts"]["しながわ水族館"] == 8
    assert summary["place_counts"]["自宅"] == 7
    assert summary["person_counts"]["太郎"] == 6
    assert summary["person_counts"]["花子"] == 4


def test_render_photo_section_matches_issue_example_format():
    records = _build_issue_example_records()

    section = render_photo_section(
        records,
        data_labels=["レシート"],
        memory_locations=["しながわ水族館"],
    )

    lines = section.splitlines()
    assert lines[0] == "## 写真"
    assert lines[1] == ""
    assert "- 撮影: 23枚（スクショ除外後 15枚）" in lines
    assert "- 場所: しながわ水族館(8枚), 自宅(7枚)" in lines
    assert "- 人物: 太郎(6枚), 花子(4枚)" in lines
    assert "- 思い出候補: 8枚（人物+場所+お気に入り）" in lines
    assert "- データ写真候補: 3枚（食べ物ラベル）" in lines
    assert "- 未分類: 4枚（Phase 3 対象）" in lines


def test_render_photo_section_unclassified_lists_filenames_for_phase3():
    records = _build_issue_example_records()

    section = render_photo_section(
        records,
        data_labels=["レシート"],
        memory_locations=["しながわ水族館"],
    )

    assert "unc0.jpg" in section
    assert "unc1.jpg" in section


def test_render_photo_section_empty_records():
    section = render_photo_section({})
    assert "- 撮影: 0枚（スクショ除外後 0枚）" in section.splitlines()
    assert "- 場所: (なし)" in section.splitlines()
    assert "- 人物: (なし)" in section.splitlines()


# --- video handling (issue #8) --------------------------------------------------


def test_summarize_records_counts_videos_separately_and_excludes_from_unclassified():
    records = {
        "VID-1": make_record(uuid="VID-1", record_type="video"),
        "VID-2": make_record(
            uuid="VID-2",
            record_type="video",
            favorite=True,
            labels=["Food"],
            persons=["太郎"],
        ),
        "UNC-1": make_record(uuid="UNC-1", place="自宅"),
    }

    summary = summarize_records(records, family_names=["太郎"], data_labels=["food"])

    assert summary["total"] == 3
    assert summary["video_count"] == 2
    assert len(summary["unclassified"]) == 1
    assert summary["unclassified"][0]["uuid"] == "UNC-1"


def test_render_photo_section_includes_video_count_line():
    records = {
        "VID-1": make_record(uuid="VID-1", record_type="video"),
        "VID-2": make_record(uuid="VID-2", record_type="video"),
        "P-1": make_record(uuid="P-1"),
    }

    section = render_photo_section(records)

    assert "- 動画: 2本（LLM解析対象外）" in section.splitlines()


def test_render_photo_section_videos_are_not_listed_as_unclassified():
    records = {
        "VID-1": make_record(
            uuid="VID-1",
            nas_filename="clip.mov",
            original_filename="IMG_9999.MOV",
            record_type="video",
        ),
    }

    section = render_photo_section(records)

    assert "clip.mov" not in section
    assert "IMG_9999.MOV" not in section
    assert "- 未分類: 0枚（Phase 3 対象）" in section.splitlines()


# --- upsert_section --------------------------------------------------------------


def test_upsert_section_creates_new_file(tmp_path):
    path = tmp_path / "2026-03-01.md"
    section = "## 写真\n\n- 撮影: 1枚\n"

    upsert_section(path, section)

    content = path.read_text(encoding="utf-8")
    assert "## 写真" in content
    assert "- 撮影: 1枚" in content


def test_upsert_section_preserves_other_sections(tmp_path):
    path = tmp_path / "2026-03-01.md"
    path.write_text(
        "# 2026-03-01\n\n## 健康\n\n- 歩数: 8000\n\n## メモ\n\n- 覚え書き\n",
        encoding="utf-8",
    )

    upsert_section(path, "## 写真\n\n- 撮影: 5枚\n")

    content = path.read_text(encoding="utf-8")
    assert "## 健康" in content
    assert "- 歩数: 8000" in content
    assert "## メモ" in content
    assert "- 覚え書き" in content
    assert "## 写真" in content
    assert "- 撮影: 5枚" in content


def test_upsert_section_replaces_existing_photo_section_only(tmp_path):
    path = tmp_path / "2026-03-01.md"
    path.write_text(
        "# 2026-03-01\n\n## 写真\n\n- 撮影: 1枚（古い）\n\n## メモ\n\n- 覚え書き\n",
        encoding="utf-8",
    )

    upsert_section(path, "## 写真\n\n- 撮影: 23枚\n")

    content = path.read_text(encoding="utf-8")
    assert "撮影: 1枚（古い）" not in content
    assert "- 撮影: 23枚" in content
    assert "## メモ" in content
    assert "- 覚え書き" in content


def test_upsert_section_is_idempotent(tmp_path):
    path = tmp_path / "2026-03-01.md"
    section = "## 写真\n\n- 撮影: 23枚\n"

    upsert_section(path, section)
    first = path.read_text(encoding="utf-8")
    upsert_section(path, section)
    second = path.read_text(encoding="utf-8")

    assert first == second


# --- CLI -------------------------------------------------------------------------


def test_build_parser_requires_date_and_out_dir():
    parser = build_parser()
    args = parser.parse_args(["2026-03-01", "--out-dir", "/tmp/facts"])
    assert args.date == "2026-03-01"
    assert args.out_dir == "/tmp/facts"
    assert args.dry_run is False


def test_build_parser_accepts_classification_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "2026-03-01",
            "--out-dir",
            "/tmp/facts",
            "--family",
            "太郎,花子",
            "--data-labels",
            "food,receipt",
            "--memory-locations",
            "しながわ水族館",
            "--dry-run",
        ]
    )
    assert args.family == "太郎,花子"
    assert args.data_labels == "food,receipt"
    assert args.memory_locations == "しながわ水族館"
    assert args.dry_run is True
