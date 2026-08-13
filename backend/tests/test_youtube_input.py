import pytest

from backend.app.core.youtube_input import normalize_playlist_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" PL_123-abc ", "PL_123-abc"),
        ("https://www.youtube.com/playlist?list=PL_123-abc", "PL_123-abc"),
        ("youtube.com/playlist?foo=1&list=PL_123-abc", "PL_123-abc"),
        ("https://youtu.be/?list=PL_123-abc", "PL_123-abc"),
        ("", ""),
        (None, ""),
        ("https://example.com/playlist?list=PL_123-abc", ""),
        ("javascript:alert(1)", ""),
        ("https://www.youtube.com/playlist?list=not valid", ""),
    ],
)
def test_normalize_playlist_id_accepts_only_supported_ids_and_hosts(value, expected):
    assert normalize_playlist_id(value) == expected
