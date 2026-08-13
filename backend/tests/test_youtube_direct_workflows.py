from types import SimpleNamespace

from backend.app.api import youtube as youtube_api
from backend.app.api.youtube import BatchUpdateInput, PublishCleanupInput, VideoAssignment
from backend.app.core.youtube_context import YouTubeRequestContext
from backend.app.services.youtube_errors import YouTubeQuotaUnavailable


def youtube_context():
    return YouTubeRequestContext(
        slot="primary",
        credentials=object(),
        quota_limiter=SimpleNamespace(),
        owner_sub="test-user",
    )


def quota_error():
    return YouTubeQuotaUnavailable(
        code="youtube_quota_safety_blocked",
        http_status=None,
        reason="safety_cap_reached",
        method="videos.update",
        bucket="general",
        reset_at="2026-08-03T00:00:00-07:00",
        confirmed_by_google=False,
        user_message="今日 YouTube 配額已達安全上限。",
    )


def metadata_payload(*people):
    return BatchUpdateInput(
        spreadsheet_url_or_id="sheet-id",
        video_type="Video",
        worksheet_name="Youtube Video",
        title_column="Youtube Title",
        description_column="Youtube Description",
        team="Team",
        assignments=[
            VideoAssignment(video_id=f"video-{index}", person=person) for index, person in enumerate(people, 1)
        ],
    )


def install_metadata_inputs(monkeypatch, people):
    monkeypatch.setattr(
        youtube_api,
        "get_sheet_headers",
        lambda *_args: ["所屬團體", "人", "Youtube Title", "Youtube Description"],
    )
    monkeypatch.setattr(
        youtube_api,
        "get_all_rows_for_sheet",
        lambda *_args: [
            {
                "所屬團體": "Team",
                "人": person,
                "Youtube Title": f"New {person}",
                "Youtube Description": f"Description {person}",
            }
            for person in people
        ],
    )
    monkeypatch.setattr(
        youtube_api,
        "fetch_video_details",
        lambda _creds, video_ids: [
            {
                "id": video_id,
                "snippet": {
                    "title": f"Old {video_id}",
                    "description": "Old description",
                    "categoryId": "22",
                    "tags": ["keep"],
                },
            }
            for video_id in video_ids
        ],
    )


def test_metadata_direct_flow_continues_after_one_video_fails(monkeypatch):
    people = ["Alice", "Bob", "Carol"]
    install_metadata_inputs(monkeypatch, people)
    calls = []

    def update(_creds, video_id, title, description, *, current_snippet):
        calls.append((video_id, title, description, current_snippet))
        if video_id == "video-2":
            raise RuntimeError("temporary update failure")
        return {"id": video_id}

    monkeypatch.setattr(youtube_api, "update_single_video_metadata", update)

    response = youtube_api.run_batch_metadata_update(
        metadata_payload(*people), creds=youtube_context(), sheet_creds=object()
    )

    assert [item["status"] for item in response["results"]] == ["succeeded", "failed", "succeeded"]
    assert response["completed"] is True
    assert response["succeeded_count"] == 2
    assert response["failed_count"] == 1
    assert [call[0] for call in calls] == ["video-1", "video-2", "video-3"]
    assert calls[0][3]["tags"] == ["keep"]


def test_metadata_quota_block_keeps_partial_results_and_stops_writes(monkeypatch):
    people = ["Alice", "Bob", "Carol"]
    install_metadata_inputs(monkeypatch, people)
    calls = []

    def update(_creds, video_id, *_args, **_kwargs):
        calls.append(video_id)
        if video_id == "video-2":
            raise quota_error()
        return {"id": video_id}

    monkeypatch.setattr(youtube_api, "update_single_video_metadata", update)

    response = youtube_api.run_batch_metadata_update(
        metadata_payload(*people), creds=youtube_context(), sheet_creds=object()
    )

    assert [item["status"] for item in response["results"]] == ["succeeded", "not_attempted", "not_attempted"]
    assert calls == ["video-1", "video-2"]
    assert response["completed"] is False
    assert response["quota_blocked"] is True
    assert response["reset_at"] == "2026-08-03T00:00:00-07:00"


def test_publish_cleanup_warning_continues_but_public_failure_stops_later_items(monkeypatch):
    raw_items = [
        {"id": f"playlist-{video_id}", "contentDetails": {"videoId": video_id}, "snippet": {"title": video_id}}
        for video_id in ("video-3", "video-1", "video-2")
    ]
    details = {
        "video-1": {
            "id": "video-1",
            "snippet": {"title": "One", "publishedAt": "2026-01-01T00:00:00Z"},
            "status": {"privacyStatus": "private"},
        },
        "video-2": {
            "id": "video-2",
            "snippet": {"title": "Two", "publishedAt": "2026-01-02T00:00:00Z"},
            "status": {"privacyStatus": "private"},
        },
        "video-3": {
            "id": "video-3",
            "snippet": {"title": "Three", "publishedAt": "2026-01-03T00:00:00Z"},
            "status": {"privacyStatus": "private"},
        },
    }
    monkeypatch.setattr(youtube_api, "fetch_playlist_items", lambda *_args: raw_items)
    monkeypatch.setattr(youtube_api, "fetch_video_details", lambda _creds, ids: [details[video_id] for video_id in ids])
    public_calls = []
    cleanup_calls = []

    def set_public(_creds, video_id, **_kwargs):
        public_calls.append(video_id)
        if video_id == "video-2":
            raise RuntimeError("cannot publish")
        return {"id": video_id}

    def cleanup(_creds, playlist_item_id):
        cleanup_calls.append(playlist_item_id)
        raise RuntimeError("cleanup unavailable")

    monkeypatch.setattr(youtube_api, "set_video_public", set_public)
    monkeypatch.setattr(youtube_api, "remove_playlist_item", cleanup)

    response = youtube_api.run_publish_and_cleanup(
        PublishCleanupInput(playlist_id="playlist"), creds=youtube_context()
    )

    assert [item["video_id"] for item in response["results"]] == ["video-1", "video-2", "video-3"]
    assert [item["status"] for item in response["results"]] == [
        "succeeded_with_warnings",
        "failed",
        "not_attempted",
    ]
    assert public_calls == ["video-1", "video-2"]
    assert cleanup_calls == ["playlist-video-1"]
    assert response["warning_count"] == 1
    assert response["completed"] is False


def test_publish_quota_after_public_keeps_completed_item_and_partial_results(monkeypatch):
    raw_items = [
        {"id": f"playlist-{video_id}", "contentDetails": {"videoId": video_id}, "snippet": {"title": video_id}}
        for video_id in ("video-1", "video-2")
    ]
    details = [
        {
            "id": video_id,
            "snippet": {"title": video_id, "publishedAt": f"2026-01-0{index}T00:00:00Z"},
            "status": {"privacyStatus": "private"},
        }
        for index, video_id in enumerate(("video-1", "video-2"), 1)
    ]
    monkeypatch.setattr(youtube_api, "fetch_playlist_items", lambda *_args: raw_items)
    monkeypatch.setattr(youtube_api, "fetch_video_details", lambda *_args: details)
    public_calls = []
    monkeypatch.setattr(
        youtube_api, "set_video_public", lambda _creds, video_id, **_kwargs: public_calls.append(video_id) or {}
    )
    monkeypatch.setattr(youtube_api, "remove_playlist_item", lambda *_args: (_ for _ in ()).throw(quota_error()))

    response = youtube_api.run_publish_and_cleanup(
        PublishCleanupInput(playlist_id="playlist"), creds=youtube_context()
    )

    assert [item["status"] for item in response["results"]] == ["succeeded_with_warnings", "not_attempted"]
    assert public_calls == ["video-1"]
    assert response["quota_blocked"] is True
    assert response["completed"] is False
    assert response["succeeded_count"] == 0
    assert response["warning_count"] == 1
