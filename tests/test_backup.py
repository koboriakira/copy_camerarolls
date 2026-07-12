from datetime import datetime
from types import SimpleNamespace

from backup import copy_one, dest_dir_for, load_state, save_state


def test_load_state_missing_file_returns_empty_set(tmp_path):
    assert load_state(tmp_path / ".backup_state.json") == set()


def test_save_and_load_state_roundtrip(tmp_path):
    state_path = tmp_path / ".backup_state.json"
    save_state(state_path, {"uuid-1", "uuid-2"})
    assert load_state(state_path) == {"uuid-1", "uuid-2"}


def test_dest_dir_for_builds_year_month_day_path(tmp_path):
    photo = SimpleNamespace(date=datetime(2026, 3, 1, 14, 23))
    assert dest_dir_for(tmp_path, photo) == tmp_path / "2026" / "03" / "01"


def test_copy_one_copies_new_file(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"fake-image-bytes")
    dest_dir = tmp_path / "dest"
    photo = SimpleNamespace(path=str(src), live_photo=False, path_live_photo=None)

    files, live = copy_one(photo, dest_dir, dry_run=False)

    assert (files, live) == (1, 0)
    assert (dest_dir / "src.jpg").exists()


def test_copy_one_skips_existing_file(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"fake-image-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    (dest_dir / "src.jpg").write_bytes(b"already-here")
    photo = SimpleNamespace(path=str(src), live_photo=False, path_live_photo=None)

    files, live = copy_one(photo, dest_dir, dry_run=False)

    assert files == 1
    assert (dest_dir / "src.jpg").read_bytes() == b"already-here"


def test_copy_one_missing_source_returns_zero(tmp_path):
    photo = SimpleNamespace(path=None, live_photo=False, path_live_photo=None)
    assert copy_one(photo, tmp_path / "dest", dry_run=False) == (0, 0)


def test_copy_one_copies_live_photo_pair(tmp_path):
    src = tmp_path / "src.heic"
    src.write_bytes(b"fake-heic")
    live_src = tmp_path / "src.mov"
    live_src.write_bytes(b"fake-mov")
    dest_dir = tmp_path / "dest"
    photo = SimpleNamespace(path=str(src), live_photo=True, path_live_photo=str(live_src))

    files, live = copy_one(photo, dest_dir, dry_run=False)

    assert (files, live) == (1, 1)
    assert (dest_dir / "src.mov").exists()


def test_copy_one_dry_run_does_not_copy(tmp_path):
    src = tmp_path / "src.jpg"
    src.write_bytes(b"fake-image-bytes")
    dest_dir = tmp_path / "dest"
    photo = SimpleNamespace(path=str(src), live_photo=False, path_live_photo=None)

    files, live = copy_one(photo, dest_dir, dry_run=True)

    assert (files, live) == (1, 0)
    assert not (dest_dir / "src.jpg").exists()
