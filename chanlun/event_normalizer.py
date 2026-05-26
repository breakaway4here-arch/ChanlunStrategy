"""
Event normalizer — dedup brief/content, generate display fields,
provide safe frontend-consumable output from raw CLS telegraph data.
"""


def normalize_event(event):
    """Normalize a single event for frontend display.

    Returns a dict with:
      display_title  — short title for card header
      display_body   — one or two sentence summary for first screen
      raw_content    — original full content (for collapsed area)
      has_redundant_content — True if brief and content are near-duplicates
    """
    title = event.get("title", "") or ""
    brief = event.get("brief", "") or ""
    content = event.get("content", "") or ""

    # Determine display_title
    display_title = title or brief[:80] or "无标题"

    # Detect brief/content redundancy
    has_redundant = _is_redundant(brief, content)

    # Build display_body
    if brief and not has_redundant:
        display_body = brief[:200]
    elif content:
        display_body = content[:200]
    else:
        display_body = ""

    # raw_content for collapsing
    raw_content = content if content else brief

    return {
        "display_title": display_title,
        "display_body": display_body,
        "raw_content": raw_content,
        "has_redundant_content": has_redundant,
    }


def _is_redundant(text_a, text_b):
    """Check if text_b is essentially a superset of text_a (brief vs content)."""
    if not text_a or not text_b:
        return False
    a = text_a.strip()
    b = text_b.strip()
    if a == b:
        return True
    if len(a) < 10 or len(b) < 10:
        return False
    # Check if a is a substring of b or vice versa
    if a in b or b in a:
        return True
    # Simple overlap ratio
    a_chars = set(a)
    b_chars = set(b)
    if not a_chars or not b_chars:
        return False
    overlap = len(a_chars & b_chars) / min(len(a_chars), len(b_chars))
    return overlap > 0.9


def normalize_events(events):
    """Apply normalize_event to a list of events."""
    for e in events:
        e.update(normalize_event(e))
    return events
