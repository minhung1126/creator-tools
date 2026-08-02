# YouTube Data API quota policy

Creator Tools keeps a durable, request-level estimate for the YouTube Data API
general bucket. It is not a Google Cloud Monitoring feed and does not include
requests made by other applications in the same Cloud project.

The official default for the general bucket is 10,000 units per day. The
current methods used by this project are recorded at their documented
per-request costs:

| Method | Units/request |
| --- | ---: |
| `playlistItems.list` | 1 |
| `videos.list` | 1 |
| `videos.update` | 50 |
| `playlistItems.delete` | 50 |

Pagination is charged per request. Before a request is sent, its documented
cost is reserved in SQLite. A safety buffer configured by the user is deducted
from the configured project limit. If the reservation would cross that policy
cap, the request is not sent and the task waits for the next reset.

The settings page separates:

- the official default (`10,000`),
- the project limit copied from Google Cloud Console,
- the Creator Tools safety buffer, and
- the local estimated usage and effective available units.

The daily boundary is midnight in `America/Los_Angeles`, calculated with the
IANA timezone database. The API returns the reset timestamp with its current
`-07:00` or `-08:00` offset; the UI renders both Pacific Time and the browser's
local time.

When Google returns HTTP 403 with reason `quotaExceeded`, the ledger changes to
`confirmed_exhausted`, sets effective availability to zero, and moves the
YouTube lane to `waiting_youtube_quota`. Those tasks remain queued with a
durable `next_attempt_at`; the queue resumes them automatically after the
Pacific midnight reset. Manual retry cannot bypass the breaker.

Quota audit data lives in `youtube_quota_daily` and `youtube_quota_events` in
`data/creator_tools.db`. The previous
`data/youtube_quota_usage.json`, if present, is imported once for the current
quota date and is not written by the new code. Keep the data directory in the
deployment volume.

References:

- [YouTube quota costs](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube API errors](https://developers.google.com/youtube/v3/docs/errors)
- [Google Cloud quotas](https://docs.cloud.google.com/docs/quotas/view-manage)
