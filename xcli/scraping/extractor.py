"""XExtractor — high-level DOM extraction for X.com timelines and profiles.

TODO: Phase 1

Will include:
- XExtractor.fetch_feed(count, comments_per) → feed dict
- XExtractor.fetch_thread_comments(url, y) → list of reply dicts
- XExtractor.research_profile(username, posts, comments_per) → profile dict
- _goto_with_auth_checks: nav primitive with auth barrier + rate-limit detection
"""
