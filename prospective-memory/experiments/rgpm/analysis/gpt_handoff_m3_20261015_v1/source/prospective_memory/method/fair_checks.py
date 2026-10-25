"""Source-level arbitration of already eligible CHECK proposals; no execution.

Used only by the opt-in fair-trigger policy. Hosts must collect proposals BEFORE
spending a query slot, enforce intention/source binding and current-evidence
eligibility, and pass the remaining actual step budget. It cannot recover a
source that an upstream bank-order filter has already suppressed.

An offer and an actual query are different events. Selection records an offer;
the host separately calls ``record_query`` when it actually issues a query,
including an actor-substituted query. Neither event proves successful retrieval,
fresh evidence, a true trigger, or completed work. Deferred proposals retain their
meaning: they are NOT WAIT/false decisions.

Sources are ordered by the oldest most-recent offer OR query, then by separate
offer/query recency and source name. Unseen sources come first. Grouping precedes
ranking, so task IDs, bank insertion order and the number of intentions watching
a source do not buy it extra priority. With a stable eligible set, positive
budget and no priority override, ignored offers rotate rather than monopolize
the slot. This is a coverage heuristic, not optimal information-value scheduling.

Caller-supplied priority sources override recency only for code-established hard
gate dependencies. Persistent priority can starve other sources; the caller must
remove fulfilled/current gates. There is no built-in special treatment of clock,
any task wording, model, dataset or source name.
"""

from dataclasses import dataclass
from typing import Iterable

from ..core import Decision


def _name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {label}")
    return value


def _names(values, label):
    if isinstance(values, (str, bytes, dict)):
        raise ValueError(f"{label} must be a collection of source IDs")
    try:
        result = tuple(_name(value, label) for value in values)
    except TypeError as exc:
        raise ValueError(f"{label} must be a collection of source IDs") from exc
    if len(result) != len(set(result)):
        raise ValueError(f"Duplicate {label}")
    return result


@dataclass(frozen=True)
class CheckGroup:
    """One source slot with every original proposal, without a chosen task."""

    source: str
    decisions: tuple[Decision, ...]


@dataclass(frozen=True)
class CheckSelection:
    selected: tuple[CheckGroup, ...]
    deferred: tuple[CheckGroup, ...]

    @property
    def selected_sources(self):
        return tuple(group.source for group in self.selected)

    @property
    def deferred_sources(self):
        return tuple(group.source for group in self.deferred)


class FairCheckArbiter:
    """Pure source scheduler with separate offer and actual-query histories.

    ``queryable_sources`` is a fixed host registry, not inferred from proposals.
    It may be empty for a push-only host. Snapshot restore cannot widen it.
    Histories use logical event sequence numbers, not environmental time.
    """

    def __init__(self, queryable_sources: Iterable[str]):
        self.queryable_sources = tuple(sorted(_names(queryable_sources, "queryable sources")))
        self._sources = frozenset(self.queryable_sources)
        self._sequence = 0
        self._offered: list[tuple[int, str]] = []
        self._queried: list[tuple[int, str]] = []
        self._last_offered: dict[str, int] = {}
        self._last_queried: dict[str, int] = {}

    def arbitrate(self, candidates: Iterable[Decision], *, budget: int,
                  priority_sources: Iterable[str] = ()) -> CheckSelection:
        """Validate, group and offer at most ``budget`` distinct sources.

        All validation is completed before histories change. Duplicate intention
        IDs are rejected (including identical rows), whereas multiple distinct
        intentions sharing a source form one group. Proposal text/evidence IDs
        are retained exactly; evidence semantics and bank membership belong to
        the caller. Evidence IDs must have the immutable tuple shape of Decision.
        """
        if type(budget) is not int or budget < 0:
            raise ValueError("budget must be a nonnegative integer")
        priorities = frozenset(_names(priority_sources, "priority sources"))
        if priorities - self._sources:
            raise ValueError("Unknown priority source")
        if isinstance(candidates, (str, bytes, dict)):
            raise ValueError("candidates must be a collection of CHECK Decisions")
        try:
            rows = tuple(candidates)
        except TypeError as exc:
            raise ValueError("candidates must be a collection of CHECK Decisions") from exc
        grouped: dict[str, list[Decision]] = {}
        seen = set()
        for row in rows:
            if not isinstance(row, Decision) or row.kind != "CHECK":
                raise ValueError("Expected a CHECK Decision")
            _name(row.intention_id, "intention ID")
            _name(row.source, "CHECK source")
            if row.source not in self._sources:
                raise ValueError("Unknown or non-queryable CHECK source")
            if not isinstance(row.reason, str):
                raise ValueError("Invalid CHECK reason")
            if not isinstance(row.evidence_ids, tuple):
                raise ValueError("CHECK evidence_ids must be a tuple")
            for evidence_id in row.evidence_ids:
                _name(evidence_id, "evidence ID")
            if len(set(row.evidence_ids)) != len(row.evidence_ids):
                raise ValueError("Duplicate evidence ID")
            if row.intention_id in seen:
                raise ValueError("Duplicate intention ID")
            seen.add(row.intention_id)
            grouped.setdefault(row.source, []).append(row)

        def rank(source):
            offered = self._last_offered.get(source, 0)
            queried = self._last_queried.get(source, 0)
            return (source not in priorities, max(offered, queried), offered, queried, source)

        # Within-group ordering is display-only, never used in the source rank.
        groups = tuple(CheckGroup(source, tuple(sorted(grouped[source], key=lambda d: d.intention_id)))
                       for source in sorted(grouped, key=rank))
        result = CheckSelection(groups[:budget], groups[budget:])
        for group in result.selected:
            self._sequence += 1
            self._offered.append((self._sequence, group.source))
            self._last_offered[group.source] = self._sequence
        return result

    def record_query(self, source: str):
        """Record an actual query/attempt, not a successful reply or an offer.

        A query need not match a previous offer. Repeated actual queries are
        distinct events and are not silently deduplicated. The host, not this
        history recorder, must enforce the real per-step execution budget.
        """
        _name(source, "queried source")
        if source not in self._sources:
            raise ValueError("Unknown or non-queryable queried source")
        self._sequence += 1
        self._queried.append((self._sequence, source))
        self._last_queried[source] = self._sequence

    def snapshot(self):
        """Return a detached JSON-compatible record of source-level history."""
        return {"version": 1, "kind": "fair_checks", "queryable_sources": list(self.queryable_sources),
                "sequence": self._sequence,
                "offered": [{"sequence": n, "source": s} for n, s in self._offered],
                "queried": [{"sequence": n, "source": s} for n, s in self._queried]}

    def restore(self, state):
        """Restore atomically, requiring identical source registry and format.

        This is structural validation, not cryptographic provenance. No pending
        proposals, intentions, truth judgments, or model configuration are stored.
        """
        fields = {"version", "kind", "queryable_sources", "sequence", "offered", "queried"}
        if (not isinstance(state, dict) or set(state) != fields
                or type(state["version"]) is not int or state["version"] != 1
                or state["kind"] != "fair_checks"
                or not isinstance(state["queryable_sources"], list)
                or state["queryable_sources"] != list(self.queryable_sources)
                or type(state["sequence"]) is not int or state["sequence"] < 0):
            raise ValueError("Invalid or source-mismatched fair-check snapshot")
        histories, last_seen, sequence_ids = {}, {}, []
        for name in ("offered", "queried"):
            if not isinstance(state[name], list):
                raise ValueError("Invalid fair-check history")
            history, last, previous = [], {}, 0
            for event in state[name]:
                if (not isinstance(event, dict) or set(event) != {"sequence", "source"}
                        or type(event["sequence"]) is not int
                        or not previous < event["sequence"] <= state["sequence"]
                        or not isinstance(event["source"], str) or event["source"] not in self._sources):
                    raise ValueError("Invalid fair-check history event")
                previous = event["sequence"]
                history.append((previous, event["source"]))
                last[event["source"]] = previous
                sequence_ids.append(previous)
            histories[name], last_seen[name] = history, last
        if (len(sequence_ids) != state["sequence"]
                or any(n != expected for expected, n in enumerate(sorted(sequence_ids), start=1))):
            raise ValueError("Duplicate or missing fair-check event sequence")
        self._sequence = state["sequence"]
        self._offered, self._queried = histories["offered"], histories["queried"]
        self._last_offered, self._last_queried = last_seen["offered"], last_seen["queried"]
