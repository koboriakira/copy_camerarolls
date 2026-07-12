import sys
from datetime import datetime
from types import SimpleNamespace

import backup
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


def test_copy_one_copies_video_file(tmp_path):
    """ismovie=True の PhotoInfo も他の写真と同様にコピー対象になることを確認する。

    copy_one は photo.path の存在だけを見てコピーするため、動画かどうかで
    分岐しない実装のはず。将来ここに ismovie による除外分岐が誤って
    追加された場合にこのテストが検知する。
    """
    src = tmp_path / "clip.mov"
    src.write_bytes(b"fake-video-bytes")
    dest_dir = tmp_path / "dest"
    photo = SimpleNamespace(
        path=str(src), live_photo=False, path_live_photo=None, ismovie=True
    )

    files, live = copy_one(photo, dest_dir, dry_run=False)

    assert (files, live) == (1, 0)
    assert (dest_dir / "clip.mov").exists()


# --- main(): 動画がバックアップ対象から漏れないことの回帰テスト（issue #8） ------


class _FakePhotosDB:
    """osxphotos.PhotosDB の代替。固定の photos リストを返す。"""

    def __init__(self, photos):
        self._photos = photos

    def photos(self):
        return self._photos


def test_main_backs_up_video_and_photo_without_filtering_by_type(tmp_path, monkeypatch):
    """db.photos() が返す ismovie=True の動画も、写真と同様に全件バックアップされる。

    main() が将来 `if photo.ismovie: continue` のような除外分岐を持ち込んだ場合に
    このテストが失敗し、回帰を検知する。
    """
    dest = tmp_path / "nas"
    dest.mkdir()

    photo_src = tmp_path / "photo.jpg"
    photo_src.write_bytes(b"fake-photo-bytes")
    video_src = tmp_path / "video.mov"
    video_src.write_bytes(b"fake-video-bytes")

    photo = SimpleNamespace(
        uuid="PHOTO-UUID",
        path=str(photo_src),
        date=datetime(2026, 3, 1, 9, 0),
        live_photo=False,
        path_live_photo=None,
        ismovie=False,
        original_filename="photo.jpg",
    )
    video = SimpleNamespace(
        uuid="VIDEO-UUID",
        path=str(video_src),
        date=datetime(2026, 3, 1, 9, 0),
        live_photo=False,
        path_live_photo=None,
        ismovie=True,
        original_filename="video.mov",
    )

    monkeypatch.setattr(backup.osxphotos, "PhotosDB", lambda: _FakePhotosDB([photo, video]))
    monkeypatch.setattr(sys, "argv", ["backup.py", "--dest", str(dest)])

    backup.main()

    assert (dest / "2026" / "03" / "01" / "photo.jpg").exists()
    assert (dest / "2026" / "03" / "01" / "video.mov").exists()

    copied_uuids = load_state(dest / backup.STATE_FILENAME)
    assert {"PHOTO-UUID", "VIDEO-UUID"} <= copied_uuids
