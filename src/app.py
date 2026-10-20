#!/usr/bin/env python3
"""Local web UI for interview_to_transcript.py (stdlib only, listens on 127.0.0.1).

    python app.py            # then open http://127.0.0.1:8765
"""

from ai_interview.web.server import main

if __name__ == "__main__":
    main()
