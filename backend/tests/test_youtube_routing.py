from types import SimpleNamespace

from backend.app.core import youtube_routing


def install_routing_fakes(monkeypatch, usage):
    monkeypatch.setattr(youtube_routing, "get_account_youtube_routing_mode", lambda _owner: "auto_primary")
    monkeypatch.setattr(youtube_routing, "get_account_active_slot", lambda _owner: "primary")
    monkeypatch.setattr(
        youtube_routing,
        "settings",
        SimpleNamespace(
            youtube_oauth_slot=lambda slot: SimpleNamespace(configured=True),
        ),
    )
    monkeypatch.setattr(
        youtube_routing,
        "credential_store",
        SimpleNamespace(
            get_youtube_public=lambda _owner, slot="primary": {"channel_id": "channel-1"},
        ),
    )
    monkeypatch.setattr(
        youtube_routing,
        "get_youtube_credentials",
        lambda _session, slot="primary": SimpleNamespace(valid=True, token=f"{slot}-token"),
    )
    monkeypatch.setattr(
        youtube_routing,
        "get_youtube_quota_tracker",
        lambda slot: SimpleNamespace(get_usage=lambda: usage[slot]),
    )


def test_auto_routing_prefers_primary_when_the_whole_request_fits(monkeypatch):
    usage = {
        "primary": {"effective_available_units": 200, "reset_at": "primary-reset"},
        "secondary": {"effective_available_units": 200, "reset_at": "secondary-reset"},
    }
    install_routing_fakes(monkeypatch, usage)

    decision = youtube_routing.choose_youtube_slot("session", "owner", estimated_units=200)

    assert decision.slot == "primary"
    assert decision.reason == "auto_primary_available"


def test_auto_routing_falls_back_then_returns_to_primary(monkeypatch):
    usage = {
        "primary": {"effective_available_units": 199, "reset_at": "primary-reset"},
        "secondary": {"effective_available_units": 200, "reset_at": "secondary-reset"},
    }
    install_routing_fakes(monkeypatch, usage)

    fallback = youtube_routing.choose_youtube_slot("session", "owner", estimated_units=200)
    assert fallback.slot == "secondary"
    assert fallback.reason == "auto_secondary_quota_insufficient"

    usage["primary"]["effective_available_units"] = 200
    recovered = youtube_routing.choose_youtube_slot("session", "owner", estimated_units=200)
    assert recovered.slot == "primary"
    assert recovered.reason == "auto_primary_available"


def test_preview_slot_hint_is_pinned_even_if_primary_recovers(monkeypatch):
    usage = {
        "primary": {"effective_available_units": 10_000, "reset_at": "primary-reset"},
        "secondary": {"effective_available_units": 200, "reset_at": "secondary-reset"},
    }
    install_routing_fakes(monkeypatch, usage)

    decision = youtube_routing.choose_youtube_slot(
        "session", "owner", estimated_units=200, slot_hint="secondary"
    )

    assert decision.slot == "secondary"
    assert decision.reason == "preview_pinned_slot"


def test_upload_estimate_separates_preview_reads_and_zero_upload_bucket_cost():
    full = youtube_routing.estimate_youtube_upload_quota(0, 0)
    after_preview = youtube_routing.estimate_youtube_upload_quota(0, 0, general_reads_spent=1)
    after_job_validation = youtube_routing.estimate_youtube_upload_quota(0, 0, general_reads_spent=2)
    resume = youtube_routing.estimate_youtube_upload_quota(0, 2, general_reads_spent=1)

    assert full["complete_workflow"] == {"general": 2, "video_uploads": 0, "total": 2}
    assert full["preview_read"] == {"general": 1, "video_uploads": 0}
    assert full["job_required"] == {"general": 1, "video_uploads": 0}
    assert full["remaining_required"] == {"general": 2, "video_uploads": 0}
    assert after_preview["remaining_required"] == {"general": 1, "video_uploads": 0}
    assert after_job_validation["remaining_required"] == {"general": 0, "video_uploads": 0}
    assert resume["complete_workflow"] == {"general": 102, "video_uploads": 0, "total": 102}
    assert resume["job_required"] == {"general": 101, "video_uploads": 0}
    assert resume["remaining_required"] == {"general": 101, "video_uploads": 0}


def test_resume_upload_does_not_read_or_require_video_upload_bucket(monkeypatch):
    usage = {
        "primary": {"effective_available_units": 101, "reset_at": "primary-reset"},
        "secondary": {"effective_available_units": 101, "reset_at": "secondary-reset"},
    }
    install_routing_fakes(monkeypatch, usage)
    monkeypatch.setattr(
        youtube_routing,
        "get_youtube_upload_quota_tracker",
        lambda _slot: (_ for _ in ()).throw(AssertionError("resume must not read upload bucket")),
    )

    decision = youtube_routing.choose_youtube_upload_slot(
        "session",
        "owner",
        item_count=0,
        upload_count=0,
        insertion_count=2,
        slot_hint="secondary",
        general_reads_spent=1,
    )

    assert decision.slot == "secondary"
    assert decision.estimated_units == 102
    assert decision.reason == "preview_pinned_slot"


def test_pinned_upload_slot_stays_secondary_when_primary_recovers(monkeypatch):
    usage = {
        "primary": {"effective_available_units": 10_000, "reset_at": "primary-reset"},
        "secondary": {"effective_available_units": 101, "reset_at": "secondary-reset"},
    }
    install_routing_fakes(monkeypatch, usage)
    monkeypatch.setattr(
        youtube_routing,
        "get_youtube_upload_quota_tracker",
        lambda slot: SimpleNamespace(get_usage=lambda: {"effective_available_units": 0, "reset_at": f"{slot}-reset"}),
    )

    decision = youtube_routing.choose_youtube_upload_slot(
        "session",
        "owner",
        item_count=0,
        upload_count=0,
        insertion_count=2,
        slot_hint="secondary",
        general_reads_spent=1,
    )

    assert decision.slot == "secondary"
    assert decision.reason == "preview_pinned_slot"


def test_workflow_estimates_are_conservative():
    assert youtube_routing.estimate_youtube_request_units("/api/v1/youtube/video-metadata") == 51
    assert youtube_routing.estimate_youtube_request_units(
        "/api/v1/youtube/batch-update",
        {"playlist_id": "playlist", "assignments": [{"video_id": "video-1"}, {"video_id": "video-2"}]},
    ) == 301
    assert youtube_routing.estimate_youtube_request_units(
        "/api/v1/youtube/batch-preview",
        {"playlist_id": "playlist", "assignments": [{"video_id": "video-1"}]},
    ) == 101
    assert youtube_routing.estimate_youtube_request_units(
        "/api/v1/youtube/publish-and-cleanup",
        {"preview_snapshot": {"video_ids": ["video-1", "video-2"]}},
    ) == 203
