import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import backup
import catalog
from catalog import (
    build_record,
    default_llm_block,
    iter_dated_dirs,
    load_catalog,
    mark_missing_files,
    rebuild,
    render,
    render_index_md,
    save_catalog,
    sync,
    update_llm_block,
    upsert_record,
    write_index_md,
)


def make_place(name):
    return SimpleNamespace(name=name)


def make_photo(
    uuid="821D9B5C-8C7D-405C-9F99-260551C71157",
    path="/library/821D9B5C-8C7D-405C-9F99-260551C71157.jpeg",
    original_filename="IMG_4021.HEIC",
    date=None,
    persons=None,
    labels=None,
    place=None,
    location=(None, None),
    favorite=False,
    albums=None,
    ai_caption="",
    screenshot=False,
    ismovie=False,
    live_photo=False,
    path_live_photo=None,
):
    return SimpleNamespace(
        uuid=uuid,
        path=path,
        original_filename=original_filename,
        date=date or datetime(2026, 3, 1, 14, 23, 11),
        persons=persons or [],
        labels=labels or [],
        place=place,
        location=location,
        favorite=favorite,
        albums=albums or [],
        ai_caption=ai_caption,
        screenshot=screenshot,
        ismovie=ismovie,
        live_photo=live_photo,
        path_live_photo=path_live_photo,
    )


# --- dest_dir_for reuse -----------------------------------------------------


def test_catalog_reuses_backup_dest_dir_for_single_source():
    assert catalog.dest_dir_for is backup.dest_dir_for


# --- build_record ------------------------------------------------------------


def test_build_record_maps_osxphotos_fields():
    photo = make_photo(
        persons=["Alice", "Bob"],
        labels=["dog", "beach"],
        place=make_place("東京都渋谷区"),
        location=(35.6595, 139.7005),
        favorite=True,
        albums=["旅行"],
        ai_caption="A dog on the beach",
    )

    record = build_record(photo, "821D9B5C-....jpeg", None, in_photos_library=True)

    assert record["schema_version"] == 1
    assert record["uuid"] == photo.uuid
    assert record["nas_filename"] == "821D9B5C-....jpeg"
    assert record["original_filename"] == "IMG_4021.HEIC"
    assert record["date"] == "2026-03-01T14:23:11"
    assert record["type"] == "photo"
    assert record["live_video_file"] is None
    assert record["osxphotos"]["persons"] == ["Alice", "Bob"]
    assert record["osxphotos"]["labels"] == ["dog", "beach"]
    assert record["osxphotos"]["ai_caption"] == "A dog on the beach"
    assert record["osxphotos"]["place"] == "東京都渋谷区"
    assert record["osxphotos"]["location"] == {"latitude": 35.6595, "longitude": 139.7005}
    assert record["osxphotos"]["favorite"] is True
    assert record["osxphotos"]["albums"] == ["旅行"]
    assert "refreshed_at" in record["osxphotos"]
    assert record["llm"] == default_llm_block()
    assert record["in_photos_library"] is True
    assert record["file_missing"] is False


def test_build_record_screenshot_type():
    photo = make_photo(screenshot=True)
    record = build_record(photo, "x.png", None)
    assert record["type"] == "screenshot"


def test_build_record_video_type():
    photo = make_photo(ismovie=True)
    record = build_record(photo, "x.mov", None)
    assert record["type"] == "video"


def test_build_record_no_place_or_location_defaults_empty():
    photo = make_photo(place=None, location=(None, None))
    record = build_record(photo, "x.jpeg", None)
    assert record["osxphotos"]["place"] == ""
    assert record["osxphotos"]["location"] is None


# --- upsert_record (llm merge) ------------------------------------------------


def test_upsert_record_preserves_existing_llm_block():
    records = {
        "UUID-1": {
            "uuid": "UUID-1",
            "llm": {
                "model": "claude-x",
                "prompt_version": "v1",
                "analyzed_at": "2026-07-01",
                "caption": "犬の写真",
                "classification": "memory",
            },
        }
    }
    new_record = {"uuid": "UUID-1", "llm": default_llm_block(), "osxphotos": {}}

    upsert_record(records, new_record)

    assert records["UUID-1"]["llm"]["classification"] == "memory"
    assert records["UUID-1"]["llm"]["caption"] == "犬の写真"


def test_upsert_record_new_uuid_keeps_empty_llm():
    records = {}
    new_record = {"uuid": "UUID-2", "llm": default_llm_block()}

    upsert_record(records, new_record)

    assert records["UUID-2"]["llm"] == default_llm_block()


def test_upsert_record_with_explicit_source():
    records = {}
    source = {"UUID-3": {"uuid": "UUID-3", "llm": {**default_llm_block(), "caption": "kept"}}}
    new_record = {"uuid": "UUID-3", "llm": default_llm_block()}

    upsert_record(records, new_record, source=source)

    assert records["UUID-3"]["llm"]["caption"] == "kept"


# --- load/save catalog (atomic write) ----------------------------------------


def test_load_catalog_missing_returns_empty_dict(tmp_path):
    assert load_catalog(tmp_path) == {}


def test_save_and_load_catalog_roundtrip(tmp_path):
    records = {"UUID-1": {"uuid": "UUID-1", "nas_filename": "a.jpg"}}
    save_catalog(tmp_path, records)

    assert load_catalog(tmp_path) == records
    assert (tmp_path / "index.json").exists()


def test_save_catalog_does_not_leave_tmp_file(tmp_path):
    save_catalog(tmp_path, {"UUID-1": {"uuid": "UUID-1"}})
    assert not (tmp_path / "index.json.tmp").exists()


def test_save_catalog_creates_directory_if_missing(tmp_path):
    dir_path = tmp_path / "2026" / "03" / "01"
    save_catalog(dir_path, {"UUID-1": {"uuid": "UUID-1"}})
    assert (dir_path / "index.json").exists()


# --- mark_missing_files -------------------------------------------------------


def test_mark_missing_files_flags_deleted_file(tmp_path):
    (tmp_path / "present.jpg").write_bytes(b"data")
    records = {
        "UUID-1": {"uuid": "UUID-1", "nas_filename": "present.jpg"},
        "UUID-2": {"uuid": "UUID-2", "nas_filename": "gone.jpg"},
    }

    mark_missing_files(tmp_path, records)

    assert records["UUID-1"]["file_missing"] is False
    assert records["UUID-2"]["file_missing"] is True
    # deletion never happens, only flagging
    assert set(records.keys()) == {"UUID-1", "UUID-2"}


# --- render_index_md -----------------------------------------------------------


def test_render_index_md_includes_persons_place_and_gps(tmp_path):
    dir_path = tmp_path / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    records = {
        "UUID-1": {
            "uuid": "UUID-1",
            "nas_filename": "UUID-1.jpeg",
            "original_filename": "IMG_1.HEIC",
            "type": "photo",
            "date": "2026-03-01T10:00:00",
            "osxphotos": {
                "persons": ["Alice"],
                "place": "渋谷",
                "location": {"latitude": 35.1, "longitude": 139.1},
                "favorite": True,
            },
            "llm": default_llm_block(),
            "in_photos_library": True,
            "file_missing": False,
        }
    }

    content = render_index_md(dir_path, records)

    assert "2026-03-01" in content
    assert "Alice" in content
    assert "渋谷" in content
    assert "35.10000" in content
    assert "139.10000" in content
    assert "★" in content


def test_render_index_md_empty_directory(tmp_path):
    dir_path = tmp_path / "2026" / "03" / "02"
    dir_path.mkdir(parents=True)
    content = render_index_md(dir_path, {})
    assert "写真なし" in content


def test_render_index_md_flags_missing_file():
    records = {
        "UUID-1": {
            "uuid": "UUID-1",
            "nas_filename": "UUID-1.jpeg",
            "original_filename": "IMG_1.HEIC",
            "type": "photo",
            "date": None,
            "osxphotos": {"persons": [], "place": "", "location": None, "favorite": False},
            "llm": default_llm_block(),
            "in_photos_library": False,
            "file_missing": True,
        }
    }
    content = render_index_md(Path("2026/03/03"), records)
    assert "欠落" in content
    assert "×" in content


def test_write_index_md_creates_file(tmp_path):
    write_index_md(tmp_path, {})
    assert (tmp_path / "index.md").exists()


# --- iter_dated_dirs -----------------------------------------------------------


def test_iter_dated_dirs_finds_only_date_directories(tmp_path):
    (tmp_path / "2026" / "03" / "01").mkdir(parents=True)
    (tmp_path / "2026" / "03" / "02").mkdir(parents=True)
    (tmp_path / "legacy_event_folder").mkdir(parents=True)

    dirs = iter_dated_dirs(tmp_path)

    assert dirs == [tmp_path / "2026" / "03" / "01", tmp_path / "2026" / "03" / "02"]


def test_iter_dated_dirs_missing_dest_returns_empty(tmp_path):
    assert iter_dated_dirs(tmp_path / "does-not-exist") == []


# --- sync ------------------------------------------------------------------


def test_sync_upserts_photo_whose_file_exists_on_nas(tmp_path):
    src = tmp_path / "library" / "821D9B5C-8C7D-405C-9F99-260551C71157.jpeg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")

    dest = tmp_path / "nas"
    dest_dir = dest / "2026" / "03" / "01"
    dest_dir.mkdir(parents=True)
    (dest_dir / src.name).write_bytes(b"fake")

    photo = make_photo(path=str(src), date=datetime(2026, 3, 1, 10, 0, 0))

    stats = sync(dest, [photo])

    assert stats == {"upserted": 1, "skipped_missing_file": 0, "directories": 1}
    catalog_data = load_catalog(dest_dir)
    assert photo.uuid in catalog_data
    assert (dest_dir / "index.md").exists()


def test_sync_skips_photo_not_yet_copied_to_nas(tmp_path):
    src = tmp_path / "library" / "no-file-on-nas.jpeg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")

    dest = tmp_path / "nas"
    photo = make_photo(path=str(src), date=datetime(2026, 3, 1))

    stats = sync(dest, [photo])

    assert stats["upserted"] == 0
    assert stats["skipped_missing_file"] == 1


def test_sync_skips_photo_with_no_path(tmp_path):
    photo = make_photo(path=None)
    stats = sync(tmp_path / "nas", [photo])
    assert stats["skipped_missing_file"] == 1


def test_sync_preserves_llm_block_written_by_photo3(tmp_path):
    src = tmp_path / "library" / "821D9B5C-8C7D-405C-9F99-260551C71157.jpeg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")

    dest = tmp_path / "nas"
    dest_dir = dest / "2026" / "03" / "01"
    dest_dir.mkdir(parents=True)
    (dest_dir / src.name).write_bytes(b"fake")

    photo = make_photo(path=str(src), date=datetime(2026, 3, 1))

    # first sync creates the record
    sync(dest, [photo])

    # simulate PHOTO-3 writing an llm analysis result
    update_llm_block(
        dest_dir,
        photo.uuid,
        {
            "model": "claude-x",
            "prompt_version": "v1",
            "analyzed_at": "2026-07-12",
            "caption": "犬の写真",
            "classification": "memory",
        },
    )

    # re-running sync (e.g. after a refresh) must not wipe the llm block
    sync(dest, [photo])

    catalog_data = load_catalog(dest_dir)
    assert catalog_data[photo.uuid]["llm"]["classification"] == "memory"
    assert catalog_data[photo.uuid]["llm"]["caption"] == "犬の写真"


def test_sync_copies_live_photo_companion_when_present(tmp_path):
    src = tmp_path / "library" / "821D9B5C-8C7D-405C-9F99-260551C71157.heic"
    live_src = tmp_path / "library" / "821D9B5C-8C7D-405C-9F99-260551C71157.mov"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")
    live_src.write_bytes(b"fake-mov")

    dest = tmp_path / "nas"
    dest_dir = dest / "2026" / "03" / "01"
    dest_dir.mkdir(parents=True)
    (dest_dir / src.name).write_bytes(b"fake")
    (dest_dir / live_src.name).write_bytes(b"fake-mov")

    photo = make_photo(
        path=str(src),
        date=datetime(2026, 3, 1),
        live_photo=True,
        path_live_photo=str(live_src),
    )

    sync(dest, [photo])

    catalog_data = load_catalog(dest_dir)
    assert catalog_data[photo.uuid]["live_video_file"] == live_src.name


# --- rebuild -----------------------------------------------------------------


def test_rebuild_flags_missing_file_instead_of_deleting_record(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    # record exists in catalog but the underlying file was manually deleted
    save_catalog(
        dir_path,
        {
            "DEAD-UUID": {
                "uuid": "DEAD-UUID",
                "nas_filename": "DEAD-UUID.jpeg",
                "osxphotos": {},
                "llm": default_llm_block(),
                "in_photos_library": True,
                "file_missing": False,
            }
        },
    )

    stats = rebuild(dest, [])

    catalog_data = load_catalog(dir_path)
    assert "DEAD-UUID" in catalog_data
    assert catalog_data["DEAD-UUID"]["file_missing"] is True
    assert stats["directories"] == 1


def test_rebuild_marks_in_photos_library_false_and_keeps_prior_metadata(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    uuid = "821D9B5C-8C7D-405C-9F99-260551C71157"
    (dir_path / f"{uuid}.jpeg").write_bytes(b"fake")

    save_catalog(
        dir_path,
        {
            uuid: {
                "uuid": uuid,
                "nas_filename": f"{uuid}.jpeg",
                "original_filename": "IMG_old.HEIC",
                "osxphotos": {"persons": ["Alice"], "place": "渋谷"},
                "llm": {**default_llm_block(), "classification": "memory"},
                "in_photos_library": True,
                "file_missing": False,
            }
        },
    )

    # photo no longer present in the current Photos library (deleted from Photos)
    stats = rebuild(dest, [])

    catalog_data = load_catalog(dir_path)
    record = catalog_data[uuid]
    assert record["in_photos_library"] is False
    assert record["osxphotos"]["persons"] == ["Alice"]
    assert record["llm"]["classification"] == "memory"
    assert stats["not_in_library"] == 1


def test_rebuild_uses_current_library_metadata_when_uuid_present(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    uuid = "821D9B5C-8C7D-405C-9F99-260551C71157"
    (dir_path / f"{uuid}.jpeg").write_bytes(b"fake")

    photo = make_photo(uuid=uuid, favorite=True, persons=["Bob"])

    stats = rebuild(dest, [photo])

    catalog_data = load_catalog(dir_path)
    record = catalog_data[uuid]
    assert record["in_photos_library"] is True
    assert record["osxphotos"]["persons"] == ["Bob"]
    assert record["osxphotos"]["favorite"] is True
    assert stats["in_library"] == 1


def test_rebuild_groups_live_photo_pair_under_one_record(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    uuid = "821D9B5C-8C7D-405C-9F99-260551C71157"
    (dir_path / f"{uuid}.heic").write_bytes(b"fake")
    (dir_path / f"{uuid}.mov").write_bytes(b"fake-mov")

    photo = make_photo(uuid=uuid)

    rebuild(dest, [photo])

    catalog_data = load_catalog(dir_path)
    assert len(catalog_data) == 1
    assert catalog_data[uuid]["live_video_file"] == f"{uuid}.mov"
    assert catalog_data[uuid]["nas_filename"] == f"{uuid}.heic"


def test_rebuild_ignores_non_uuid_named_files(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    (dir_path / "IMG_1234.JPG").write_bytes(b"legacy file, out of v1 scope")

    stats = rebuild(dest, [])

    catalog_data = load_catalog(dir_path)
    assert catalog_data == {}
    assert stats["records"] == 0


# --- render command ------------------------------------------------------------


def test_render_command_regenerates_md_from_json_only(tmp_path):
    dest = tmp_path / "nas"
    dir_path = dest / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    save_catalog(dir_path, {"UUID-1": {"uuid": "UUID-1", "nas_filename": "a.jpg"}})

    stats = render(dest)

    assert stats["rendered"] == 1
    assert (dir_path / "index.md").exists()


def test_render_command_with_explicit_dirs(tmp_path):
    dir_path = tmp_path / "2026" / "03" / "01"
    dir_path.mkdir(parents=True)
    save_catalog(dir_path, {})

    stats = render(tmp_path, dirs=[dir_path])

    assert stats["rendered"] == 1


# --- update_llm_block (PHOTO-3 hook) --------------------------------------------


def test_update_llm_block_updates_record_and_rerenders_md(tmp_path):
    save_catalog(tmp_path, {"UUID-1": {"uuid": "UUID-1", "nas_filename": "a.jpg", "llm": {}}})

    result = update_llm_block(
        tmp_path,
        "UUID-1",
        {"model": "claude-x", "prompt_version": "v1", "classification": "memory"},
    )

    assert result["llm"]["classification"] == "memory"
    assert result["llm"]["model"] == "claude-x"
    catalog_data = load_catalog(tmp_path)
    assert catalog_data["UUID-1"]["llm"]["classification"] == "memory"
    assert (tmp_path / "index.md").exists()


def test_update_llm_block_missing_uuid_raises(tmp_path):
    save_catalog(tmp_path, {})
    try:
        update_llm_block(tmp_path, "MISSING", {"classification": "memory"})
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


# --- schema sanity -------------------------------------------------------------


# --- CLI arg parsing (regression: --dest after subcommand must not fall back to
# --- DEFAULT_DEST silently; see incident where this bug caused a real write to
# --- the production NAS mount instead of the intended path) -------------------


def test_cli_dest_after_subcommand_is_respected():
    parser = catalog.build_parser()
    for command in ("sync", "rebuild", "render"):
        args = parser.parse_args([command, "--dest", "/tmp/example-nas"])
        assert args.dest == "/tmp/example-nas", command


def test_cli_dest_defaults_when_omitted():
    parser = catalog.build_parser()
    args = parser.parse_args(["render"])
    assert args.dest == catalog.DEFAULT_DEST


def test_cli_sync_limit_option():
    parser = catalog.build_parser()
    args = parser.parse_args(["sync", "--dest", "/tmp/example-nas", "--limit", "10"])
    assert args.limit == 10
    assert args.dest == "/tmp/example-nas"


def test_index_json_is_valid_json_after_sync(tmp_path):
    src = tmp_path / "library" / "821D9B5C-8C7D-405C-9F99-260551C71157.jpeg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"fake")

    dest = tmp_path / "nas"
    dest_dir = dest / "2026" / "03" / "01"
    dest_dir.mkdir(parents=True)
    (dest_dir / src.name).write_bytes(b"fake")

    photo = make_photo(path=str(src), date=datetime(2026, 3, 1))
    sync(dest, [photo])

    with open(dest_dir / "index.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data[photo.uuid]["schema_version"] == 1
