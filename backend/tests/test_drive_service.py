from backend.app.services import drive_service


def test_video_detection_accepts_video_mime_or_extension_only():
    assert drive_service.is_video_file({"mimeType": "video/mp4", "name": "clip.bin"}) is True
    assert drive_service.is_video_file({"mimeType": "application/octet-stream", "name": "clip.MP4"}) is True
    assert drive_service.is_video_file({"mimeType": "application/pdf", "name": "clip.pdf"}) is False


def test_folder_resolution_marks_non_video_children_as_skipped(monkeypatch):
    folder = {
        "id": "folder-1",
        "name": "影片資料夾",
        "mimeType": "application/vnd.google-apps.folder",
    }
    children = [
        {"id": "video-1", "name": "clip.mp4", "mimeType": "video/mp4"},
        {"id": "document-1", "name": "notes.pdf", "mimeType": "application/pdf"},
        {
            "id": "nested-folder",
            "name": "子資料夾",
            "mimeType": "application/vnd.google-apps.folder",
        },
    ]
    monkeypatch.setattr(drive_service, "get_drive_metadata", lambda _credentials, _item_id: folder)
    monkeypatch.setattr(drive_service, "list_folder_children", lambda _credentials, _metadata: children)

    result = drive_service.resolve_drive_source(object(), "folder-1")

    assert result["source_kind"] == "folder"
    assert [item["preview_status"] for item in result["items"]] == ["ready", "skipped", "skipped"]
    assert result["items"][0]["skip_reason"] is None
    assert all(item["skip_reason"] == "非影片檔案或子資料夾" for item in result["items"][1:])
