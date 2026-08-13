from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api import youtube as youtube_api
from backend.app.api.youtube import BatchUpdateInput, PublishCleanupInput, VideoAssignment
from backend.app.core.youtube_context import YouTubeRequestContext


def youtube_context():
    return YouTubeRequestContext(
        slot="primary",
        credentials=object(),
        quota_limiter=SimpleNamespace(),
        owner_sub="preview-security-user",
    )


def playlist_item(video_id: str, item_id: str | None = None):
    return {
        "id": item_id or f"playlist-{video_id}",
        "contentDetails": {"videoId": video_id},
        "snippet": {"title": video_id},
    }


def video_detail(video_id: str):
    return {
        "id": video_id,
        "snippet": {
            "title": f"Old {video_id}",
            "description": "old",
            "categoryId": "22",
        },
        "status": {"privacyStatus": "private"},
    }


def test_batch_preview_includes_each_video_and_marks_unassigned_items(monkeypatch):
    monkeypatch.setattr(youtube_api, "get_sheet_headers", lambda *_args: ["所屬團體", "人", "標題", "描述"])
    monkeypatch.setattr(
        youtube_api,
        "get_all_rows_for_sheet",
        lambda *_args: [{"所屬團體": "Team", "人": "Alice", "標題": "New", "描述": "Description"}],
    )
    monkeypatch.setattr(
        youtube_api, "fetch_playlist_items", lambda *_args: [playlist_item("video-1"), playlist_item("video-2")]
    )
    monkeypatch.setattr(
        youtube_api,
        "fetch_video_details",
        lambda _context, ids: [video_detail(video_id) for video_id in ids],
    )

    payload = BatchUpdateInput(
        spreadsheet_url_or_id="sheet-id",
        playlist_id="playlist",
        worksheet_name="工作表",
        title_column="標題",
        description_column="描述",
        team="Team",
        assignments=[
            VideoAssignment(video_id="video-1", person="Alice"),
            VideoAssignment(video_id="video-2", person="不編輯"),
        ],
    )
    response = youtube_api.create_batch_metadata_preview(payload, creds=youtube_context(), sheet_creds=object())

    assert [item["video_id"] for item in response["plan"]] == ["video-1", "video-2"]
    assert response["plan"][0]["status"] == "ready"
    assert response["plan"][1]["status"] == "skipped"
    assert response["plan"][1]["reason"] == "未指定人物"
    assert response["preview_snapshot"]["video_ids"] == ["video-1", "video-2"]
    assert response["preview_token"]


def test_publish_stale_playlist_has_zero_writes(monkeypatch):
    initial = [playlist_item("video-1")]
    changed = [playlist_item("video-2")]
    reads = iter((initial, changed))
    writes = []

    monkeypatch.setattr(youtube_api, "fetch_playlist_items", lambda *_args: next(reads))
    monkeypatch.setattr(
        youtube_api, "fetch_video_details", lambda _context, ids: [video_detail(video_id) for video_id in ids]
    )
    monkeypatch.setattr(youtube_api, "set_video_public", lambda *_args, **_kwargs: writes.append("public"))
    monkeypatch.setattr(youtube_api, "remove_playlist_item", lambda *_args: writes.append("remove"))

    with pytest.raises(HTTPException) as caught:
        youtube_api.run_publish_and_cleanup(PublishCleanupInput(playlist_id="playlist"), creds=youtube_context())

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "stale_preview"
    assert writes == []


def test_batch_stale_sheet_has_zero_writes(monkeypatch):
    headers = ["所屬團體", "人", "標題", "描述"]
    first_rows = [{"所屬團體": "Team", "人": "Alice", "標題": "New", "描述": "Description"}]
    changed_rows = [{"所屬團體": "Team", "人": "Alice", "標題": "Changed", "描述": "Description"}]
    rows = iter((first_rows, changed_rows))
    writes = []

    monkeypatch.setattr(youtube_api, "get_sheet_headers", lambda *_args: headers)
    monkeypatch.setattr(youtube_api, "get_all_rows_for_sheet", lambda *_args: next(rows))
    monkeypatch.setattr(
        youtube_api, "fetch_video_details", lambda _context, ids: [video_detail(video_id) for video_id in ids]
    )
    monkeypatch.setattr(youtube_api, "update_single_video_metadata", lambda *_args, **_kwargs: writes.append("update"))

    payload = BatchUpdateInput(
        spreadsheet_url_or_id="sheet-id",
        worksheet_name="工作表",
        title_column="標題",
        description_column="描述",
        team="Team",
        assignments=[VideoAssignment(video_id="video-1", person="Alice")],
    )
    with pytest.raises(HTTPException) as caught:
        youtube_api.run_batch_metadata_update(payload, creds=youtube_context(), sheet_creds=object())

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "stale_preview"
    assert writes == []
