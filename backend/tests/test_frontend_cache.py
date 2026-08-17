import asyncio

from starlette.requests import Request
from starlette.responses import Response

from backend.app import main
from backend.app.main import HASHED_ASSET_CACHE_CONTROL, HTML_CACHE_CONTROL, frontend_cache_control


def _security_response(path, media_type):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "http_version": "1.1",
    }
    request = Request(scope)

    async def call_next(_request):
        return Response("ok", media_type=media_type)

    return asyncio.run(main.security_headers(request, call_next))


def test_html_requires_revalidation():
    assert frontend_cache_control("/", "text/html; charset=utf-8") == HTML_CACHE_CONTROL
    assert frontend_cache_control("/dashboard", "text/html") == "no-cache, max-age=0, must-revalidate"


def test_hashed_javascript_and_css_are_immutable_for_one_year():
    assert (
        frontend_cache_control("/assets/index-a1b2c3d4.js", "text/javascript; charset=utf-8")
        == HASHED_ASSET_CACHE_CONTROL
    )
    assert frontend_cache_control("/assets/index-a1b2c3d4.css", "text/css; charset=utf-8") == HASHED_ASSET_CACHE_CONTROL


def test_unhashed_or_non_frontend_assets_do_not_get_long_lived_cache():
    assert frontend_cache_control("/assets/runtime.js", "text/javascript") is None
    assert frontend_cache_control("/assets/index-a1b2c3d4.js", "application/json") is None


def test_security_middleware_applies_cache_policy_to_html_and_hashed_assets():
    homepage = _security_response("/", "text/html")
    script = _security_response("/assets/index-a1b2c3d4.js", "application/javascript")

    assert homepage.headers["cache-control"] == HTML_CACHE_CONTROL
    assert script.headers["cache-control"] == HASHED_ASSET_CACHE_CONTROL
