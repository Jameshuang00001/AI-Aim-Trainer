"""History comparisons and natural AI feedback without credentials or network."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from coach_app.report_format import session_comparison, checked_coaching, conversational_report
from coach_app.session_reader import find_previous_session

class ConversationalFeedbackTests(unittest.TestCase):
    def session(self, ident='current', start='2026-10-27T15:00:00Z', end='2026-10-27T15:05:00Z', hits=18, shots=20):
        return dict(session_id=ident, started_at=start, ended_at=end, shots=shots, hits=hits,
                    misses=shots-hits, accuracy=hits/shots*100, avg_reaction_ms=900, shots_detail=[])

    def test_accuracy_uses_counts_and_percentage_points(self):
        current, previous=self.session(), self.session(hits=16)
        current['accuracy']=100  # comparison must use actual hit/shot counts
        c=session_comparison(current,previous)
        self.assertEqual(c['accuracy_change_percentage_points'],10)
        self.assertIn('80.0%',c['explanation'])
        self.assertIn('90.0%',c['explanation'])
        self.assertIn('not saved',c['explanation'])

    def test_confounded_and_small_comparison_labelled(self):
        current=self.session(hits=9,shots=10);current['aim_corrections']=[{}]
        c=session_comparison(current,self.session(hits=16))
        self.assertIn('Assistance use differs',c['explanation'])
        self.assertIn('small sample',c['explanation'])
        self.assertFalse(session_comparison(current)['available'])
        self.assertFalse(session_comparison(current,{'shots':0})['available'])

    def test_previous_is_completed_distinct_chronological_not_mtime(self):
        current=self.session()
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            def save(name,s): (folder/name).write_text(json.dumps(s))
            save('current.json',current)
            save('old.json',self.session('older','2026-10-26T12:00:00Z','2026-10-26T12:05:00Z'))
            save('prior.json',self.session('prior','2026-10-27T14:00:00Z','2026-10-27T14:05:00Z'))
            save('future.json',self.session('future','2026-10-28T14:00:00Z','2026-10-28T14:05:00Z'))
            save('overlap.json',self.session('overlap','2026-10-27T14:59:00Z','2026-10-27T15:01:00Z'))
            save('repeat.json',dict(current,started_at='2026-10-26T00:00:00Z',ended_at='2026-10-26T00:10:00Z'))
            (folder/'bad.json').write_text('{')
            self.assertEqual(find_previous_session(current,folder/'current.json')['session_id'],'prior')
            self.assertIsNone(find_previous_session(dict(current,started_at='bad'),folder/'current.json'))

    def test_natural_coaching_not_limited_to_drill_id(self):
        notes=dict(feedback='Nice step up in accuracy. Keep an eye on the time you spend lining up each shot.',
                   possible_reason='You might have allowed more time to aim; the data cannot confirm that. Try repeating the same setup.',
                   next_drill='Keep the same mode and sensitivity, turn assistance off, and take 20 shots. Compare accuracy and target-to-hit time.')
        checked=checked_coaching(json.dumps(notes))
        report=conversational_report(self.session(),checked,self.session(hits=16),source='Mock online')
        self.assertIn('Nice step up',report)
        self.assertIn('hypothesis, not a measured cause',report)
        self.assertIn('+10.0 percentage points',report)
        self.assertIn(notes['next_drill'],report)
        for invalid in ['{}','[]',json.dumps(dict(notes,feedback='')),json.dumps(dict(notes,feedback='x'*2201))]:
            with self.assertRaises(ValueError):checked_coaching(invalid)

    def test_model_narrative_success_and_comparison_payload(self):
        notes=dict(feedback='A solid session.',possible_reason='You might be taking more care before clicking.',next_drill='Take 20 manual shots in the same mode.')
        from coach_app.test_nebius_client import NebiusClientTests
        helper=NebiusClientTests()
        result, client=helper.run_model([(json.dumps(notes),'stop')],self.session())
        self.assertIn('AI interpretation',result)
        self.assertIn('A solid session.',result)
        request=client.chat.completions.create.call_args.kwargs
        payload=json.loads(request['messages'][1]['content'].split('\n',1)[1])
        self.assertIn('previous_session_comparison',payload)
        self.assertFalse(payload['previous_session_comparison']['available'])
