"""DOM-to-Python parsing utilities for X.com content.

TODO: Phase 1

Will include:
- parse_metric_count: "12.3K" → 12300, "1.2M" → 1_200_000, etc.
- parse_post_id_from_href: extract numeric tweet ID from /status/ URLs
- parse_join_date: "Joined June 2009" → "2009-06"
- extract_links_from_node: resolve t.co links via aria-label / data-expanded-url
"""
