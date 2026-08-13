from backend.app.core.preview import (
    build_preview_token,
    input_digest,
    playlist_snapshot,
    playlist_snapshot_from_preview,
    sheet_snapshot,
    verify_preview_token,
)


def test_preview_token_is_bound_to_owner_slot_operation_and_snapshot():
    playlist = playlist_snapshot([{"id": "item-1", "contentDetails": {"videoId": "video-1"}}])
    sheet = sheet_snapshot("sheet-1", "工作表", ["人", "標題"], [{"人": "甲", "標題": "新標題"}])
    request_digest = input_digest({"video_ids": playlist["video_ids"], "team": "團體"})
    token = build_preview_token(
        owner_sub="owner-a",
        youtube_slot="secondary",
        operation="youtube.batch_metadata",
        playlist_id="playlist-1",
        playlist=playlist,
        sheet=sheet,
        request_digest=request_digest,
    )

    common = {
        "youtube_slot": "secondary",
        "operation": "youtube.batch_metadata",
        "playlist_id": "playlist-1",
        "playlist": playlist,
        "sheet": sheet,
        "request_digest": request_digest,
    }
    assert verify_preview_token(token, owner_sub="owner-a", **common) is True
    assert verify_preview_token(token, owner_sub="owner-b", **common) is False
    assert verify_preview_token(token, owner_sub="owner-a", **{**common, "youtube_slot": "primary"}) is False
    assert (
        verify_preview_token(token, owner_sub="owner-a", **{**common, "operation": "youtube.publish_cleanup"}) is False
    )
    assert (
        verify_preview_token(token, owner_sub="owner-a", **{**common, "playlist": {**playlist, "video_ids": []}})
        is False
    )


def test_preview_snapshots_preserve_order_and_exclude_provider_payload():
    raw_items = [
        {"id": "item-1", "contentDetails": {"videoId": "video-1"}, "snippet": {"title": "私密標題"}},
        {"id": "item-missing", "snippet": {"title": "不完整項目"}},
        {"id": "item-2", "contentDetails": {"videoId": "video-2"}},
    ]

    snapshot = playlist_snapshot(raw_items)
    preview_snapshot = playlist_snapshot_from_preview(
        [
            {"playlist_item_id": "item-1", "video_id": "video-1"},
            {"playlist_item_id": "item-missing", "video_id": ""},
            {"playlist_item_id": "item-2", "video_id": "video-2"},
        ]
    )

    assert preview_snapshot == playlist_snapshot([raw_items[0], raw_items[2]])
    assert snapshot["video_ids"] == ["video-1", "", "video-2"]
    assert snapshot["video_count"] == 3
    assert "私密標題" not in str(snapshot)
