from datetime import datetime
from types import SimpleNamespace

from offload_candidates import (
    MISSING_ON_NAS,
    SAFE,
    SIZE_MISMATCH,
    collect_candidates,
    evaluate_candidate,
    format_size,
    nas_path_for,
    render_report,
)


def _photo(
    uuid="UUID-1",
    path="/local/src.jpg",
    date=None,
    screenshot=False,
    ismovie=False,
):
    return SimpleNamespace(
        uuid=uuid,
        path=path,
        date=date or datetime(2026, 3, 1, 12, 0),
        screenshot=screenshot,
        ismovie=ismovie,
    )


def test_nas_path_for_builds_path_from_dest_dir_for_and_filename(tmp_path):
    photo = _photo(path=str(tmp_path / "src.jpg"), date=datetime(2026, 3, 1))
    dest = tmp_path / "nas"

    assert nas_path_for(dest, photo) == dest / "2026" / "03" / "01" / "src.jpg"


def test_evaluate_candidate_returns_none_when_local_path_missing(tmp_path):
    photo = _photo(path=None)

    assert evaluate_candidate(photo, tmp_path, {"UUID-1"}) is None


def test_evaluate_candidate_returns_none_when_local_file_not_on_disk(tmp_path):
    photo = _photo(path=str(tmp_path / "does-not-exist.jpg"))

    assert evaluate_candidate(photo, tmp_path, {"UUID-1"}) is None


def test_evaluate_candidate_returns_none_when_uuid_not_backed_up(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"1234")
    photo = _photo(uuid="UUID-1", path=str(src))

    assert evaluate_candidate(photo, tmp_path, backed_up_uuids=set()) is None


def test_evaluate_candidate_safe_when_sizes_match(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"1234")
    nas_dest = tmp_path / "nas"
    photo = _photo(uuid="UUID-1", path=str(src), date=datetime(2026, 3, 1))
    nas_file = nas_dest / "2026" / "03" / "01" / "src.jpg"
    nas_file.parent.mkdir(parents=True)
    nas_file.write_bytes(b"1234")

    record = evaluate_candidate(photo, nas_dest, {"UUID-1"})

    assert record["status"] == SAFE
    assert record["local_size"] == record["nas_size"] == 4
    assert record["uuid"] == "UUID-1"
    assert record["type"] == "photo"


def test_evaluate_candidate_size_mismatch_when_sizes_differ(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"12345678")
    nas_dest = tmp_path / "nas"
    photo = _photo(uuid="UUID-1", path=str(src), date=datetime(2026, 3, 1))
    nas_file = nas_dest / "2026" / "03" / "01" / "src.jpg"
    nas_file.parent.mkdir(parents=True)
    nas_file.write_bytes(b"1234")

    record = evaluate_candidate(photo, nas_dest, {"UUID-1"})

    assert record["status"] == SIZE_MISMATCH
    assert record["local_size"] == 8
    assert record["nas_size"] == 4


def test_evaluate_candidate_missing_on_nas_when_nas_file_absent(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"1234")
    nas_dest = tmp_path / "nas"
    photo = _photo(uuid="UUID-1", path=str(src), date=datetime(2026, 3, 1))

    record = evaluate_candidate(photo, nas_dest, {"UUID-1"})

    assert record["status"] == MISSING_ON_NAS
    assert record["nas_size"] is None


def test_evaluate_candidate_marks_video_type(tmp_path):
    src = tmp_path / "clip.mov"
    src.write_bytes(b"1234")
    nas_dest = tmp_path / "nas"
    photo = _photo(uuid="UUID-1", path=str(src), date=datetime(2026, 3, 1), ismovie=True)

    record = evaluate_candidate(photo, nas_dest, {"UUID-1"})

    assert record["type"] == "video"


def test_collect_candidates_skips_non_candidates_and_filters_by_type(tmp_path):
    dest = tmp_path / "nas"

    photo_ok = _photo(uuid="UUID-1", path=str(tmp_path / "a.jpg"), date=datetime(2026, 3, 1))
    (tmp_path / "a.jpg").write_bytes(b"1234")
    nas_a = dest / "2026" / "03" / "01" / "a.jpg"
    nas_a.parent.mkdir(parents=True)
    nas_a.write_bytes(b"1234")

    photo_video = _photo(
        uuid="UUID-2",
        path=str(tmp_path / "b.mov"),
        date=datetime(2026, 3, 1),
        ismovie=True,
    )
    (tmp_path / "b.mov").write_bytes(b"12345678")
    nas_b = dest / "2026" / "03" / "01" / "b.mov"
    nas_b.write_bytes(b"12345678")

    photo_not_backed_up = _photo(
        uuid="UUID-3", path=str(tmp_path / "c.jpg"), date=datetime(2026, 3, 1)
    )
    (tmp_path / "c.jpg").write_bytes(b"1")

    photo_icloud_only = _photo(uuid="UUID-4", path=None)

    backed_up = {"UUID-1", "UUID-2"}
    photos = [photo_ok, photo_video, photo_not_backed_up, photo_icloud_only]

    all_records = collect_candidates(photos, dest, backed_up)
    assert {r["uuid"] for r in all_records} == {"UUID-1", "UUID-2"}

    video_only = collect_candidates(photos, dest, backed_up, type_filter="video")
    assert {r["uuid"] for r in video_only} == {"UUID-2"}


def test_format_size_scales_units():
    assert format_size(500) == "500.0B"
    assert format_size(2048) == "2.0KB"
    assert format_size(5 * 1024 * 1024) == "5.0MB"
    assert format_size(3 * 1024 * 1024 * 1024) == "3.0GB"


def test_render_report_separates_safe_and_warnings_and_sorts_by_size(tmp_path):
    dest = tmp_path / "nas"
    records = [
        {
            "uuid": "UUID-1",
            "type": "photo",
            "date": datetime(2026, 3, 1),
            "local_path": tmp_path / "small.jpg",
            "nas_path": dest / "small.jpg",
            "local_size": 100,
            "nas_size": 100,
            "status": SAFE,
        },
        {
            "uuid": "UUID-2",
            "type": "video",
            "date": datetime(2026, 3, 2),
            "local_path": tmp_path / "big.mov",
            "nas_path": dest / "big.mov",
            "local_size": 9000,
            "nas_size": 9000,
            "status": SAFE,
        },
        {
            "uuid": "UUID-3",
            "type": "photo",
            "date": datetime(2026, 3, 3),
            "local_path": tmp_path / "bad.jpg",
            "nas_path": dest / "bad.jpg",
            "local_size": 500,
            "nas_size": None,
            "status": MISSING_ON_NAS,
        },
    ]

    report = render_report(records)

    safe_section, warning_section = report.split("## 警告")
    big_index = safe_section.index("big.mov")
    small_index = safe_section.index("small.jpg")
    assert big_index < small_index  # サイズの大きい順
    assert "2件" in safe_section.splitlines()[0]  # safe は2件（missing_on_nasは除外）
    assert "1件" in warning_section.splitlines()[0]
    assert "bad.jpg" in warning_section
    assert "small.jpg" not in warning_section
    assert "big.mov" not in warning_section


def test_render_report_empty_lists_show_placeholder():
    report = render_report([])
    assert "(該当なし)" in report
    assert "(なし)" in report
