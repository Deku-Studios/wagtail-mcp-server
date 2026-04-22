"""Test-only Django app exercising every Wagtail block shape.

Lives inside ``tests/`` so the published wheel does not ship it. The
intent is to give the test suite a real Wagtail page model to walk
without depending on Lex's ``apps.cms`` (the library has to stand alone
for any Wagtail shop, not just Lex).
"""
