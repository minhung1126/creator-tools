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
