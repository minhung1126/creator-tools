import pytest

from backend.app.core.instagram_publish_store import InstagramPublishStore


def _job(source_folder_id, file_id, status="published", media_id="media-1"):
    return {
        "source_folder_id": source_folder_id,
        "status": "completed",
        "items": [
            {
                "file_id": file_id,
                "file_name": "reel.mp4",
                "status": status,
                "media_id": media_id if status == "published" else None,
            }
        ],
    }


def test_store_finds_published_file_by_normalized_source_folder(tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    created = store.create(_job("https://drive.google.com/drive/folders/source-1", "file-1"))

    record = store.find_published_record("source-1", "file-1")

    assert record["job_id"] == created["id"]
    assert record["item"]["media_id"] == "media-1"


def test_store_skips_duplicate_publish_reservation(tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    store.create(_job("source-1", "file-1"))

    duplicate = store.create(
        {
            "source_folder_id": "source-1",
            "status": "queued",
            "items": [{"file_id": "file-1", "status": "queued"}],
        }
    )

    assert duplicate["items"][0]["status"] == "skipped"
    assert "已發布過" in duplicate["items"][0]["error"]
    assert duplicate["items"][0]["duplicate_media_id"] == "media-1"


def test_store_lists_and_deletes_published_history_item(tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    created = store.create(_job("source-1", "file-1"))

    history = store.list_history()

    assert len(history) == 1
    assert history[0]["job_id"] == created["id"]
    assert history[0]["file_id"] == "file-1"
    assert history[0]["media_id"] == "media-1"

    deleted = store.delete_history_item(created["id"], "file-1")

    assert deleted["record_id"] == f"{created['id']}:file-1"
    assert store.list_history() == []
    assert store.find_published_record("source-1", "file-1") is None


def test_store_does_not_delete_history_while_job_is_active(tmp_path):
    store = InstagramPublishStore(tmp_path / "jobs.json")
    job = _job("source-1", "file-1")
    job["status"] = "running"
    created = store.create(job)

    with pytest.raises(RuntimeError, match="仍在處理中"):
        store.delete_history_item(created["id"], "file-1")

    assert len(store.list_history()) == 1
