"""Robust financial number parsing.

Handles the messy number formats that appear in real-world financial
spreadsheets and PDFs:
  - Parenthetical negatives: (1,234) -> -1234
  - Currency symbols: $1,234.56 -> 1234.56
  - Percentages: 12.3% -> 0.123 (if pct_is_ratio) or 12.3
  - Em-dashes / en-dashes as zero: -- -> 0.0
  - Standalone hyphen as zero: - -> 0.0
  - Accounting underscores: 1_234 -> 1234
  - Textual no-data: "n/a", "nil" -> None
"""

from __future__ import annotations

import re

# Words that mean "no data" (not zero)
_NO_DATA_RE = re.compile(
    r"^\s*(?:n/?a|nil|null|none|na)\s*$",
    re.IGNORECASE,
)

# Dash-like characters that mean zero (not missing)
_DASH_ZERO = frozenset({"-", "\u2014", "\u2013", "\u2012", "\u2015"})


def parse_number(raw, *, pct_is_ratio: bool = False) -> float | None:
    """Parse a messy financial value into a float or None.

    Parameters
    ----------
    raw : str | int | float | None
        The raw cell value.
    pct_is_ratio : bool
        If True, percentages like "12.3%" are returned as 0.123 (ratio).
        If False (default), returned as 12.3 (percentage points).

    Returns
    -------
    float | None
        Parsed value, or None if the input represents missing data.
    """
    if raw is None:
        return None

    # NaN
    if isinstance(raw, float) and raw != raw:
        return None

    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw).strip()
    if not s:
        return None

    # Textual no-data ("n/a", "nil", "none") — but NOT dashes
    if _NO_DATA_RE.match(s):
        return None

    # Dash-like characters = zero
    if s in _DASH_ZERO:
        return 0.0

    # Parentheses-negative: (1,234) or (12.3%)
    paren_neg = s.startswith("(") and s.endswith(")")

    # Strip currency symbols, spaces, underscores
    cleaned = re.sub(r"[$\u00a3\u20ac\s_]", "", s)

    # Strip trailing %
    is_pct = cleaned.endswith("%")
    if is_pct:
        cleaned = cleaned[:-1]

    # Strip parentheses
    cleaned = cleaned.strip("()")

    # Remove commas
    cleaned = cleaned.replace(",", "")

    # Check for regular negative: starts with '-' followed by a digit
    # (standalone '-' already handled above as zero)
    regular_neg = False
    if cleaned.startswith("-") and len(cleaned) > 1 and cleaned[1].isdigit():
        regular_neg = True
        cleaned = cleaned[1:]

    # Extract numeric part
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not m:
        return None

    try:
        val = float(m.group(0))
    except ValueError:
        return None

    # Apply percentage
    if is_pct and pct_is_ratio:
        val = val / 100.0

    # Apply negative
    if paren_neg or regular_neg:
        val = -val

    return val


def parse_number_raw(raw) -> float | None:
    """Simpler alias — parse without percentage ratio conversion."""
    return parse_number(raw, pct_is_ratio=False)
