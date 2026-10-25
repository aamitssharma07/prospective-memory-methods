"""Bounded calendar-removal ambiguity helper.

This is not a schedule parser. It narrows only the existing removal-word guard;
negation, relative dates, ranges, chronology and supported-day extraction remain
the caller's responsibility. The source-bound registration guard uses this helper.
"""

import re


_REMOVAL = re.compile(r"\b(?:remove|drop|lift|relax|clear)\b", re.IGNORECASE)
_BULLET = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|(?:\d+|[A-Za-z])[.)])\s+\S")
_HEADING = re.compile(r"^\s*#{1,6}\s+\S")
_OPEN_END = re.compile(
    r"\b(?:remove|drop|lift|relax|clear|the|a|an|this|that|these|those|its|my|your|our|"
    r"their|of|on|for|from|to|and|or|with|without)\s*$", re.IGNORECASE)
_REFERENTIAL_REMOVAL = re.compile(
    r"\b(?:remove|drop|lift|relax|clear)\s+(?:(?:the|a|an|my|your|our|their)\s+)?"
    r"(?:it|them|this|that|these|those)\b", re.IGNORECASE)
_CONSTRAINT_TARGET = re.compile(
    r"\b(?:restrictions?|constraints?|limits?|rules?|requirements?|schedules?)\b", re.IGNORECASE)


def _unfinished_removal(text):
    """An obviously incomplete removal phrase must not be split by layout."""
    stripped = text.rstrip()
    tail = stripped.rstrip(".!?").rstrip()  # Punctuation cannot supply a missing object.
    return bool(_REMOVAL.search(stripped) and
                (tail.endswith(":") or _OPEN_END.search(tail)))


def _logical_units(text):
    """Separate explicit headings/sibling bullets; retain uncertain attachments.

    Ordinary line wraps and blank lines do not prove clause completion. Nested
    bullets remain attached to the containing unit. No sentence/comma splitting
    or token-distance heuristic is used to infer independent obligations.
    """
    units, active = [], []
    bullet_indent = None

    def flush():
        nonlocal active, bullet_indent
        if active:
            units.append("\n".join(active))
        active, bullet_indent = [], None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if active:
                active.append(line)
            continue
        bullet = _BULLET.match(line)
        indent = len(line) - len(line.lstrip(" \t"))
        is_heading = bool(_HEADING.match(line) or (stripped.endswith(":") and not bullet))
        nested = bullet_indent is not None and indent > bullet_indent
        unfinished = bool(active and _unfinished_removal("\n".join(active)))

        if (bullet or is_heading) and not nested and not unfinished:
            flush()
            active.append(line)
            if bullet:
                bullet_indent = len(bullet.group("indent"))
            # Retain a heading with a following plain continuation: e.g.
            # "Monday restriction:\nRemove it." is not two independent clauses.
            # A following sibling bullet establishes the next structural unit.
        else:
            active.append(line)
    flush()
    return units


def has_calendar_removal_clause(text, calendar_words):
    """Whether a removal verb has unresolved attachment to calendar language.

    ``calendar_words`` is the caller's EXISTING compiled calendar-word regex;
    this helper deliberately neither broadens nor replaces that vocabulary.
    True means retain conservative ambiguity, not that removal was proven.
    False clears only this removal-word check, never other calendar protections.

    Explicit headings and sibling bullets cannot contaminate each other merely
    through co-occurrence. Unfinished or referential removal targets (such as
    'remove it' or 'drop the restriction') cannot establish independence from
    calendar context elsewhere, so remain ambiguous even across layout markers.
    Constraint/schedule nouns anywhere in a removal-containing unit keep that
    uncertainty, including modified phrases such as 'remove the old rule'.
    Wrapped/nested/unclear clauses stay together, including
    ``Remove the\nMonday restriction``. A physical action and weekday inside one
    inseparable unit can still be rejected; semantic attachment is not inferred.
    """
    if not isinstance(text, str) or not isinstance(calendar_words, re.Pattern):
        raise TypeError("Expected text and the caller's compiled calendar-word pattern")
    if not _REMOVAL.search(text) or not calendar_words.search(text):
        return False
    return any(_REMOVAL.search(unit) and (calendar_words.search(unit)
               or _unfinished_removal(unit) or _REFERENTIAL_REMOVAL.search(unit)
               or _CONSTRAINT_TARGET.search(unit))
               for unit in _logical_units(text))
