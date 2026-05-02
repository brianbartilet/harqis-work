"""
Unit tests for `workflows.hud.helpers.text`.
"""

import pytest

from workflows.hud.helpers.text import truncate


@pytest.mark.parametrize("text,width,expected", [
    ("hello", 10, "hello"),                                       # fits
    ("hello world", 11, "hello world"),                           # fits exactly
    ("hello world!", 11, "hello wo..."),                          # overflow → trimmed + ...
    ("abcdefghij", 5, "ab..."),                                   # tight overflow
    ("ab", 2, "ab"),                                              # width <= len, fits
    ("abcd", 3, "abc"),                                           # width <= 3 → no ellipsis room
    ("abcd", 1, "a"),                                             # width=1 → hard slice
    ("abcd", 0, ""),                                              # width=0 → empty
    ("", 5, ""),                                                  # empty input
    (None, 5, ""),                                                # None input → empty
    (12345, 4, "1..."),                                           # int coerced
    (3.14, 6, "3.14"),                                            # float coerced (fits)
])
def test__truncate(text, width, expected):
    assert truncate(text, width) == expected
