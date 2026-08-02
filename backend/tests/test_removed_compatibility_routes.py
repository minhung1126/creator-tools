from backend.app.main import app


def _registered_routes():
    registered = set()

    def collect(routes, prefix=""):
        for route in routes:
            route_path = getattr(route, "path", "")
            current_path = f"{prefix}{route_path}"
            for method in getattr(route, "methods", set()):
                registered.add((current_path, method))
            nested = getattr(route, "routes", None)
            if nested:
                collect(nested, current_path)
            included_router = getattr(route, "original_router", None)
            if included_router is not None:
                included_prefix = f"{prefix}{included_router.prefix}" if not prefix else prefix
                collect(included_router.routes, included_prefix)

    collect(app.routes)
    return registered


def test_compatibility_routes_are_not_registered():
    registered = _registered_routes()

    removed = {
        ("/api/v1/settings", "GET"),
        ("/api/v1/settings", "POST"),
        ("/api/v1/youtube/batch-update-legacy", "POST"),
        ("/api/v1/youtube/publish-and-cleanup-legacy", "POST"),
    }

    assert registered.isdisjoint(removed)


def test_current_scoped_settings_routes_remain_registered():
    registered = _registered_routes()

    assert ("/api/v1/settings/system", "GET") in registered
    assert ("/api/v1/settings/shared", "GET") in registered
