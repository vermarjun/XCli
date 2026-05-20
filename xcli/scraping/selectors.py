"""Stable X.com selectors — single source of truth.

TODO: Phase 1

All data-testid constants, URL path patterns, and structural selectors will
live here.  Every other module imports constants from this file; no raw
CSS selector strings appear outside this module.

Rules (enforced by pre-commit grep in Phase 4):
- No class-name selectors (X auto-generates and rotates class strings per deploy).
- No text-content selectors (locale-dependent).
- Engagement counts: parse digits from aria-label, not text.
"""
