"""Flask entry point for the productized dashboard service."""

from __future__ import annotations

from video_review_agent.service import create_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)
