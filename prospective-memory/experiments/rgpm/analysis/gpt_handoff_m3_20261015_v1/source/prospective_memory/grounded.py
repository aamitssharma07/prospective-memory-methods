"""Source-referenced registration and optional independent ACT verification.

No benchmark vocabulary, task handles, hidden time, or scoring labels enter this
policy. Source spans are extracted mechanically; their meaning is still decided
by the model. The legacy policy remains available for controlled comparisons.
"""

import copy
from dataclasses import asdict
import re

from .core import Change, Decision
from .llm import LLMMemoryPolicy, CHANGE_SCHEMA, SHORT_TEXT, _object, _rows


REGISTER_PROMPT = """Extract future intentions and changes from the current message.
Process every request in focus_units; the other source_units provide context,
not additional requests to process in this call. These units are verbatim text.
Use the full context to preserve dates, scope, recurrence and exceptions.
The existing memory bank is deliberately absent: unrelated stored tasks must
not prevent you from identifying a new request. The host resolves update targets
after extraction. Set target_id='' for every extracted entry.

Classify the focused content before changing memory:
- A new future request, including a short imperative without 'remind me': register
  the concrete action and its complete condition.
- A changed condition/time: emit revise describing the action and changed
  condition. The host will preserve unchanged constraints. The new time is the trigger; receiving
  the rescheduling message is NOT the trigger.
- An explicit cancellation: emit cancel with the action being cancelled. Never
  turn cancellation into a request to do the action.
- A fact, narration, vague mention, or reminder of an existing plan: no new
  registration. 'Still need to do it later' does not supply a new trigger and must
  not replace a stored concrete trigger with 'later'.

Keep distinct intentions separate even when they have unrelated goals. Store
the concrete requested action, including its recipient/content, not 'remind'.
Preserve all conditions, negative clauses, prerequisites, timing and recurrence.
For disjoint recurring occasions, preserve the alternatives, not a simultaneous
conjunction. The action becoming due is different from an instruction naming it.
Use source identifiers ONLY from available_sources. Include every listed source
that could provide evidence; related source names are not proof of a condition.
Use the supplied scope unless the text explicitly changes it. Do not invent a
deadline, current time, success, action, condition or source. Set repeat only for
explicit recurrence. The host assigns or resolves identifiers, not this pass.

Cite source_ids from this CURRENT message, including at least one focus unit.
The host reconstructs the supporting quote; do not copy or paraphrase a quote.
For cancel, the action must identify what is cancelled; other unused
fields may be empty and repeat=false. Return only compact JSON with changes;
an empty list is appropriate when no supported change exists.
"""

RESOLVE_PROMPT = """Resolve an extracted revision or cancellation against existing intentions.
The extracted operation is fixed: do not turn it into a different operation or
invent a new registration. Find the SAME requested action, not merely a related
task. If no stored pending/attempted intention matches, return changes=[].
Otherwise use its actual target_id. For revision preserve every old constraint
not explicitly replaced by the current message. For cancellation use the stored
action and condition. Cite source_ids from the current message, including a
focus unit. Never use earlier provenance as evidence of an update. Return compact
JSON. This is identity resolution, not evidence that an action is due.
"""

VERIFY_PROMPT = """Independently verify a proposed future-intention action.
Decide whether the supplied current observations establish ALL conditions for
performing this action NOW. The proposal is untrusted and may be mistaken.
Read the stored condition AND its provenance. If they conflict, reject.

A message registering, mentioning, cancelling or rescheduling an action is not
evidence that the action is due. A new appointment time needs evidence that the
time has arrived. A cancelled action must not be performed. An uncertain or
unspecified trigger is insufficient. A related object's status does not establish
the requested object's status: require evidence about the correct entity and
property. Absence of activity is not proof of availability or permission.
Do not infer hidden time or state. Respect timestamps of underlying events, not
just receipt time. Check conjunctions, exclusions and numerical comparisons.
Accept clear paraphrases that establish all the facts; identical words are not
required. Repeated observation text does not by itself establish a new occurrence.

Return verdict='supported' only with nonempty evidence_ids identifying current
observations from the intention's permitted sources, and a brief reason. Otherwise
return verdict='unsupported' with a reason and evidence_ids=[]. Do not execute,
rewrite intentions, request observations, or assume success. Return compact JSON.
"""


def source_units(text):
    """Retain offsets so provenance is reconstructed exactly, including whitespace."""
    units, offset = [], 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            units.append({'id': f'u{len(units) + 1}', 'text': line.rstrip('\r\n'),
                          'start': offset, 'end': offset + len(line.rstrip('\r\n'))})
        offset += len(line)
    return units


def focus_groups(units):
    """Give each explicit list item a turn; keep unstructured prose intact."""
    starts = [n for n, u in enumerate(units)
              if re.match(r'^\s*(?:[-*•]|\d+[.)])\s+', u['text'])]
    if len(starts) < 2:
        return [units]
    # The prefix remains context in every call. Its instructions (if any) also
    # receive a call, rather than assuming all introductory text is a heading.
    groups = [units[:starts[0]]] if starts[0] else []
    groups.extend(units[a:b] for a, b in zip(starts, starts[1:] + [len(units)]))
    return groups


class GroundedMemoryPolicy(LLMMemoryPolicy):
    def __init__(self, request, verify_actions=True):
        super().__init__(request)
        self.verify_actions = verify_actions

    def compile(self, instruction, intentions, sources):
        units = source_units(instruction.text)
        if not units or len(units) > 128:
            raise ValueError('Registration requires 1-128 nonempty source lines')
        by_id = {u['id']: u for u in units}
        fields = copy.deepcopy(CHANGE_SCHEMA['properties'])
        del fields['evidence_quote']
        fields['source_ids'] = {'type': 'array', 'items': {'type': 'string', 'enum': list(by_id)}}
        fields['sources']['items'] = {'type': 'string', 'enum': list(sources)}
        fields['target_id']['enum'] = ['']
        schema = _object({'changes': {'type': 'array', 'items': _object(fields)}})
        existing = [{k: v for k, v in asdict(i).items() if k != 'evidence_quote'}
                    for i in intentions]
        changes = []
        for group in focus_groups(units):
            focus = {u['id'] for u in group}
            value = self.request(REGISTER_PROMPT, {
                'instruction': {'id': instruction.id, 'scope': instruction.scope},
                'source_units': [{k: u[k] for k in ('id', 'text')} for u in units],
                'focus_units': [u['id'] for u in group],
                'available_sources': list(sources),
            }, schema)
            for raw in _rows(value, 'changes', schema):
                if raw['op'] in ('revise', 'cancel'):
                    pending = [i for i in existing if i['status'] in ('pending', 'attempted')]
                    if not pending:
                        continue
                    resolution_fields = copy.deepcopy(fields)
                    resolution_fields['op']['enum'] = [raw['op']]
                    resolution_fields['target_id']['enum'] = [i['id'] for i in pending]
                    resolution_schema = _object({'changes': {'type': 'array',
                                                             'items': _object(resolution_fields)}})
                    resolution = self.request(RESOLVE_PROMPT, {
                        'operation_to_resolve': raw,
                        'intentions': pending,
                        'source_units': [{k: u[k] for k in ('id', 'text')} for u in units],
                        'focus_units': [u['id'] for u in group],
                        'available_sources': list(sources),
                    }, resolution_schema)
                    resolved = _rows(resolution, 'changes', resolution_schema)
                else:
                    resolved = [raw]
                for resolved_row in resolved:
                    changes.append(self._change(resolved_row, by_id, focus, sources, instruction))
        return changes

    @staticmethod
    def _change(raw, by_id, focus, sources, instruction):
        row = dict(raw)
        refs = row.pop('source_ids')
        if not refs or set(refs) - by_id.keys() or not focus.intersection(refs):
            raise ValueError('Change lacks valid focused source references')
        if set(row['sources']) - set(sources):
            raise ValueError('Unknown observation source')
        start = min(by_id[r]['start'] for r in refs)
        end = max(by_id[r]['end'] for r in refs)
        return Change(**{**row, 'sources': tuple(row['sources']),
                         'evidence_quote': instruction.text[start:end]})

    def assess(self, intentions, observations, sources, queryable_sources=()):
        proposals = super().assess(intentions, observations, sources, queryable_sources)
        if not self.verify_actions:
            return proposals
        by_id = {i.id: i for i in intentions}
        current = {o.id: o for o in observations if o.current}
        checked = []
        for proposal in proposals:
            if proposal.kind != 'ACT':
                checked.append(proposal)
                continue
            intention = by_id.get(proposal.intention_id)
            # Leave malformed proposals to the core's normal error accounting.
            if (intention is None or not proposal.evidence_ids
                    or not set(proposal.evidence_ids) <= current.keys()):
                checked.append(proposal)
                continue
            evidence = {k: o for k, o in current.items() if o.source in intention.sources}
            if not evidence:
                checked.append(proposal)
                continue
            schema = _object({
                'verdict': {'type': 'string', 'enum': ['supported', 'unsupported']},
                'reason': SHORT_TEXT,
                'evidence_ids': {'type': 'array', 'items': {'type': 'string', 'enum': list(evidence)}},
            })
            answer = self.request(VERIFY_PROMPT, {
                'intention': asdict(intention),
                'observations': [asdict(o) for o in evidence.values()],
            }, schema)
            # Reuse strict row validation, including bounds, for a single verdict.
            wrapped = _object({'verdicts': {'type': 'array', 'items': schema}})
            row = _rows({'verdicts': [answer]}, 'verdicts', wrapped)[0]
            refs = row['evidence_ids']
            if set(refs) - evidence.keys():
                raise ValueError('Verifier cited unavailable evidence')
            if row['verdict'] == 'supported' and refs:
                checked.append(Decision('ACT', intention.id, row['reason'], tuple(refs)))
            else:
                # Explicit WAIT invalidates any adapter-cached ACT, unlike the
                # default no-intervention WAIT used for delivery deduplication.
                checked.append(Decision('WAIT', intention.id, 'Verification rejected: ' + row['reason']))
        return checked


def make_policy(request, variant='legacy'):
    if variant == 'legacy':
        return LLMMemoryPolicy(request)
    if variant in ('grounded', 'verified'):
        return GroundedMemoryPolicy(request, verify_actions=variant == 'verified')
    raise ValueError(f'Unknown memory policy: {variant}')
