"""Synthetic checks for the optional task-only semantic completion interface."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coldstart.data import Corpus
from coldstart.pipeline import main
from coldstart.rules import offline
from coldstart.task_review import SYSTEM, batches, review_completions
from llm import BudgetExceeded, Client, ModelError
from test_core import make_input, task


class Stub:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def json(self, stage, system, payload, max_tokens):
        self.calls.append((stage, system, payload, max_tokens))
        return self.response(payload) if callable(self.response) else self.response


class TaskReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = make_input(Path(self.temp.name) / 'input')
        self.corpus = Corpus(self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def answer(self, payload, message='Report sent', state=1):
        source = next(q for q in payload['q'] if 'report' in payload['m'][q[1]][1].lower())
        index = next(i for i in source[4] if payload['m'][i][1] == message)
        return {'r': [[source[0], state, index]]}

    def test_model_can_resolve_paraphrase_rules_leave_open(self):
        self.corpus.message['t3']['body'] = 'All set; check your inbox.'
        baseline = offline(self.corpus)
        loop = next(v for v in baseline['open_loops'] if v['source_msg'] == 't1')
        self.assertEqual(loop['status'], 'open')
        before = copy.deepcopy(loop)
        model = Stub(lambda p: self.answer(p, 'All set; check your inbox.'))
        stats = review_completions(self.corpus, baseline['open_loops'], model)
        self.assertEqual((loop['status'], loop['closed_by']), ('done', 't3'))
        self.assertEqual(stats['resolved'], 1)
        for key in ('title', 'source_msg', 'owner', 'type', 'chat_id', 'due'):
            self.assertEqual(loop[key], before[key])

    def test_abstention_keeps_pending_task_unchanged(self):
        loops = [task()]
        before = copy.deepcopy(loops)
        review_completions(self.corpus, loops, Stub({'r': []}))
        self.assertEqual(loops, before)

    def test_model_can_confirm_contextual_done_rejected_by_ack_guard(self):
        self.corpus.message['t3']['body'] = 'Done'
        loops = [task()]
        review_completions(self.corpus, loops, Stub(lambda p: self.answer(p, 'Done')))
        self.assertEqual((loops[0]['status'], loops[0]['closed_by']), ('done', 't3'))

    def test_cancelled_task_uses_official_dropped_status(self):
        self.corpus.message['t3']['body'] = 'We no longer need that document.'
        loops = [task()]
        review_completions(self.corpus, loops, Stub(lambda p: self.answer(p, 'We no longer need that document.', 2)))
        self.assertEqual(loops[0]['status'], 'dropped')

    def test_unknown_source_cross_chat_and_malformed_updates_are_ignored(self):
        loops = [task()]
        def invalid(p):
            own = p['q'][0]
            return {'r': [[999, 1, own[4][0]], [0, 1, own[1]], [0, True, own[4][0]], ['0', 1, own[4][0]], {'status': 1}]}
        stats = review_completions(self.corpus, loops, Stub(invalid))
        self.assertEqual(loops[0]['status'], 'open')
        self.assertEqual(stats['invalid_updates'], 5)

    def test_cross_chat_evidence_from_another_task_is_rejected(self):
        loops = [task(), task(source='t4', owner='v', chat_id='direct_v', title='Send invoice')]
        def invalid(p):
            first, second = p['q']
            return {'r': [[first[0], 1, second[4][0]]]}
        review_completions(self.corpus, loops, Stub(invalid))
        self.assertTrue(all(v['status'] == 'open' for v in loops))

    def test_duplicate_task_verdicts_are_rejected(self):
        loops = [task()]
        def duplicate(p):
            row = self.answer(p)['r'][0]
            return {'r': [row, row]}
        stats = review_completions(self.corpus, loops, Stub(duplicate))
        self.assertEqual(stats['invalid_updates'], 2)
        self.assertEqual(loops[0]['status'], 'open')

    def test_provider_failure_and_budget_keep_baseline(self):
        for error in (ModelError('synthetic failure'), BudgetExceeded('budget')):
            loops = [task()]
            model = Stub({})
            with patch.object(model, 'json', side_effect=error):
                stats = review_completions(self.corpus, loops, model)
            self.assertEqual(loops[0]['status'], 'open')
            self.assertTrue(stats['failed_batches'] or stats['budget_exhausted'])

    def test_compact_payload_deduplicates_full_text_and_uses_numeric_references(self):
        loops = [task(), task()]
        payload, allowed = next(batches(self.corpus, loops))
        messages = [r[1] for r in payload['m']]
        self.assertEqual(messages.count('Report sent'), 1)
        self.assertTrue(all(isinstance(r[0], int) for r in payload['m']))
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False, separators=(',', ':'))), 6000)
        self.assertEqual(set(payload), {'m', 'q'})
        self.assertEqual(len(allowed), 2)

    def test_clipped_long_messages_cannot_be_closing_proof(self):
        self.corpus.message['t3']['body'] = 'Report sent ' + 'x' * 500
        payload, allowed = next(batches(self.corpus, [task()]))
        self.assertNotIn('t3', allowed[0].values())

    def test_already_closed_tasks_are_not_sent(self):
        model = Stub({'r': []})
        review_completions(self.corpus, [task(status='done', closed_by='t3')], model)
        self.assertEqual(model.calls, [])

    def test_opt_in_only_reviews_tasks_and_replays_cache(self):
        rows = [json.loads(l) for l in (self.folder / 'messages.jsonl').read_text().splitlines()]
        next(r for r in rows if r['id'] == 't3')['body'] = 'All set; check your inbox.'
        (self.folder / 'messages.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        self.corpus = Corpus(self.folder)
        baseline = offline(self.corpus)
        requests = []
        def transport(client, body, timeout):
            requests.append(body)
            p = json.loads(body['messages'][1]['content'])
            value = self.answer(p, 'All set; check your inbox.')
            return {'choices': [{'message': {'content': json.dumps(value)}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 80, 'completion_tokens': 10}}
        env = {'XPERT_MODE': 'offline', 'XPERT_TASK_REVIEW': '1', 'LLM_BASE_URL': 'http://localhost:8765/v1',
               'LLM_API_KEY': 'synthetic-local-placeholder', 'LLM_MODEL': 'replaceable-local-model',
               'XPERT_CACHE_DIR': str(Path(self.temp.name) / 'cache')}
        with patch.dict(os.environ, env), patch.object(Client, '_request', transport):
            out, report = main(self.folder, Path(self.temp.name) / 'hybrid.json')
            replay, cached = main(self.folder, Path(self.temp.name) / 'replay.json')
        for key in ('people', 'organisations', 'chats', 'goals'):
            self.assertEqual(out[key], baseline[key])
        self.assertEqual(len(out['open_loops']), len(baseline['open_loops']))
        self.assertEqual(out, replay)
        self.assertEqual(len(requests), 1)
        self.assertEqual(report['mode'], 'offline+task_review')
        self.assertEqual(report['task_review']['resolved'], 1)
        self.assertEqual(requests[0]['messages'][0]['content'], SYSTEM)
        self.assertEqual(requests[0]['max_tokens'], 256)
        self.assertEqual(cached['usage']['api_calls'], 0)

    def test_opt_in_requires_configuration_and_excludes_full_model_mode(self):
        for env in ({'XPERT_MODE': 'offline', 'XPERT_TASK_REVIEW': '1', 'LLM_API_KEY': ''},
                    {'XPERT_MODE': 'model', 'XPERT_TASK_REVIEW': '1'}):
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                main(self.folder, Path(self.temp.name) / 'invalid.json')


if __name__ == '__main__':
    unittest.main()
