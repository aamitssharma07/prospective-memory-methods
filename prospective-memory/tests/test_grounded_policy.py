"""Check evidence boundaries and wiring; fixtures do not measure LLM reasoning."""
import unittest
from prospective_memory.core import Engine, Instruction, Intention, Observation
from prospective_memory.grounded import GroundedMemoryPolicy, make_policy


def change(refs, **extra):
    return dict(op='register', action='Send digest', condition='Review approved',
                sources=['events'], scope='', repeat=False, target_id='',
                source_ids=refs, **extra)


class GroundedPolicyTests(unittest.TestCase):
    def test_multiline_list_has_independent_coverage_and_exact_provenance(self):
        calls = []
        text = 'For this week:\r\n- When A, do X.\r\n- When B, do Y.'
        def request(system, payload, schema):
            focus = payload['focus_units']
            calls.append(focus)
            return {'changes': [] if focus == ['u1'] else [change(focus)]}
        p = GroundedMemoryPolicy(request)
        changes = p.compile(Instruction('i', text), [], ('events',))
        self.assertEqual(calls, [['u1'], ['u2'], ['u3']])
        self.assertEqual([c.evidence_quote for c in changes], ['- When A, do X.', '- When B, do Y.'])
        self.assertTrue(all(c.evidence_quote in text for c in changes))

    def test_multiple_spans_keep_original_intervening_text(self):
        p = GroundedMemoryPolicy(lambda *a: {'changes': [change(['u1', 'u3'])]})
        text = 'When approved,\n\nwith both signatures,\nsubmit the digest.'
        self.assertEqual(p.compile(Instruction('i', text), [], ('events',))[0].evidence_quote, text)

    def test_fabricated_or_unfocused_citations_are_rejected(self):
        for refs in ([], ['old_message'], ['u2']):
            p = GroundedMemoryPolicy(lambda *a: {'changes': [change(refs)]})
            with self.assertRaises(ValueError):
                p.compile(Instruction('i', 'Plan:\n- When A, X\n- When B, Y'), [], ('events',))

    def test_cancellation_cites_current_message_and_closes_intention(self):
        def request(system, payload, schema):
            row = change(['u1'])
            if 'operation_to_resolve' in payload:
                row.update(op='cancel', target_id=payload['intentions'][0]['id'])
            elif 'Cancel' in payload['source_units'][0]['text']:
                row.update(op='cancel')
            return {'changes': [row]}
        p = GroundedMemoryPolicy(request)
        e = Engine(p.compile, p.assess, ('events',))
        e.ingest(Instruction('a', 'When approved, send digest.'))
        e.ingest(Instruction('b', 'Cancel the digest request.'))
        i = next(iter(e.intentions.values()))
        self.assertEqual(i.status, 'cancelled')
        self.assertEqual(i.evidence_quote, 'Cancel the digest request.')
        self.assertEqual(e.errors, [])

    def test_new_request_extraction_is_independent_of_existing_bank(self):
        payloads = []
        def request(system, payload, schema):
            payloads.append(payload)
            self.assertNotIn('intentions', payload)
            return {'changes': [change(['u1'])]}
        p = GroundedMemoryPolicy(request)
        old = Intention('old', 'Water the fern', 'soil dry', ('events',))
        p.compile(Instruction('i', 'When review approved, send digest.'), [old], ('events',))
        self.assertEqual(len(payloads), 1)

    def test_resolution_cannot_turn_revision_into_cancellation(self):
        def request(system, payload, schema):
            row = change(['u1'])
            row.update(op='revise')
            if 'operation_to_resolve' in payload:
                row.update(op='cancel', target_id='old')
            return {'changes': [row]}
        p = GroundedMemoryPolicy(request)
        with self.assertRaises(ValueError):
            p.compile(Instruction('i', 'Move digest to 19:00.'),
                      [Intention('old', 'Send digest', 'At 18:00', ('events',))], ('events',))

    def test_verification_vetoes_act_and_does_not_expose_proposal_reason(self):
        calls = []
        def request(system, payload, schema):
            calls.append(payload)
            if 'decisions' in schema['properties']:
                return {'decisions': [dict(kind='ACT', intention_id='pm_1',
                    reason='Untrusted proposed reasoning', evidence_ids=['e'], source='')]}
            return dict(verdict='unsupported', reason='Only a scheduling notice', evidence_ids=[])
        p = GroundedMemoryPolicy(request)
        i = Intention('pm_1', 'Send digest', 'At 17:00', ('events',))
        result = p.assess([i], [Observation('e', 'Send at 17:00 instead.')], ('events',))
        self.assertEqual(result[0].kind, 'WAIT')
        self.assertTrue(result[0].reason.startswith('Verification rejected:'))
        self.assertNotIn('proposal', calls[1])
        self.assertNotIn('Untrusted proposed reasoning', str(calls[1]))

    def test_verification_requires_current_allowed_evidence(self):
        def request(system, payload, schema):
            if 'decisions' in schema['properties']:
                return {'decisions': [dict(kind='ACT', intention_id='pm_1',
                    reason='Ready', evidence_ids=['e'], source='')]}
            return dict(verdict='supported', reason='Ready', evidence_ids=['fabricated'])
        p = GroundedMemoryPolicy(request)
        with self.assertRaises(ValueError):
            p.assess([Intention('pm_1', 'Send', 'Ready', ('events',))],
                     [Observation('e', 'Ready')], ('events',))

    def test_verified_act_reaches_core_and_duplicate_is_suppressed(self):
        def request(system, payload, schema):
            if 'changes' in schema['properties']: return {'changes': [change(['u1'])]}
            if 'decisions' in schema['properties']:
                return {'decisions': [dict(kind='ACT', intention_id='pm_000001',
                    reason='Ready', evidence_ids=['e'], source='')]}
            return dict(verdict='supported', reason='Explicit approval', evidence_ids=['e'])
        p = make_policy(request, 'verified')
        e = Engine(p.compile, p.assess, ('events',))
        e.ingest(Instruction('i', 'When approved, send digest.'))
        self.assertEqual(e.tick([Observation('e', 'Review approved')])[0].kind, 'ACT')
        self.assertEqual(e.tick([Observation('e', 'Review approved')])[0].kind, 'WAIT')


if __name__ == '__main__': unittest.main()
