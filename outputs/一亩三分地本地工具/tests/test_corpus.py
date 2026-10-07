import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

import corpus
import daily
import settings
from library import Library
from rules import choose_phrase, site_day
from tests.test_mood import days_ago


class CorpusTests(unittest.TestCase):
    def source(self, raw, **changes):
        return dict(repository='https://github.com/common-voice/common-voice', revision='a' * 40,
                    path='server/data/zh-CN/cn.txt', file='source.txt', license='CC0-1.0',
                    kind='modern', sha256=hashlib.sha256(raw).hexdigest(), **changes)

    def test_build_preserves_source_positions_and_refuses_changed_source(self):
        raw = '希望过很好的生活\n政府希望大家生活美好\n希望过很好的生活\n'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.txt'
            path.write_bytes(raw)
            source = self.source(raw)
            data = corpus.build_corpus([source], directory)
            self.assertEqual(data['entries'], [['希望过很好的生活', 0, 0, 0]])
            path.write_bytes(raw + b'changed')
            with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
                corpus.build_corpus([source], directory)
            for value in ('..', '.', '../source.txt', '/source.txt'):
                with self.assertRaisesRegex(ValueError, 'invalid_corpus_sources'):
                    corpus.build_corpus([{**source, 'file': value}], directory)
            with self.assertRaisesRegex(ValueError, 'invalid_corpus_sources'):
                corpus.build_corpus([{**source, 'repository': []}], directory)
            with self.assertRaisesRegex(ValueError, 'invalid_corpus_sources'):
                corpus.build_corpus([{**source, 'repository': 'https://example.com/unlicensed', 'license': None}], directory)

    def test_tampered_or_incomplete_corpus_cannot_be_published(self):
        raw = '希望过很好的生活\n'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.txt'
            path.write_bytes(raw)
            data = corpus.build_corpus([self.source(raw)], directory)
            output = Path(directory) / 'corpus.json'
            output.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(corpus.load_corpus(output), [('希望过很好的生活', 'modern')])
            data['entries'][0][0] = '未经验证的另一句话'
            output.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid_journal_corpus'):
                corpus.load_corpus(output)
            data['entries'][0][1] = 9
            data['sha256'] = corpus._digest(data['entries'])
            output.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid_journal_corpus'):
                corpus.load_corpus(output)
            output.write_text('{broken', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid_journal_corpus'):
                corpus.load_corpus(output)

    def test_shipped_corpus_is_large_valid_and_has_attributed_poetry(self):
        entries = corpus.load_corpus(settings.JOURNAL_CORPUS_FILE)
        self.assertGreater(len(entries), 30000)
        self.assertTrue(all('——' in text for text, kind in entries if kind == 'poetry'))

    def test_punctuation_attribution_and_high_overlap_do_not_evade_history(self):
        text = '春风轻轻吹过山间树林，阳光慢慢落在清澈溪水上。'
        recent = [text + '——作者']
        alternatives = [(text.replace('，', '、'), 'modern'), (text.replace('溪水', '泉水'), 'modern')]
        with patch('corpus.JOURNAL_STYLE', 'modern'):
            self.assertIsNone(corpus.choose_corpus_phrase('开心', alternatives, recent, Random(7)))
        pool = {'开心': [text.replace('溪水', '泉水')]}
        self.assertIsNone(choose_phrase('开心', pool, recent, Random(7)))

    def test_explicit_modern_mode_never_falls_back_to_poetry_and_mixed_can(self):
        entries = [('春眠不觉晓，处处闻啼鸟。——孟浩然', 'poetry')]
        with patch('corpus.JOURNAL_STYLE', 'modern'):
            self.assertIsNone(corpus.choose_corpus_phrase('开心', entries, [], Random(0)))
        with patch('corpus.JOURNAL_STYLE', 'mixed'):
            self.assertEqual(corpus.choose_corpus_phrase('开心', entries, [], Random(0)), entries[0][0])
        self.assertIsNone(corpus.choose_corpus_phrase(settings.CHECKIN_MOOD_DEFAULT, entries, [], Random(0)))

    def test_poetry_extracts_original_paragraph_and_author_and_rejects_war(self):
        raw = json.dumps([{'author': '孟浩然', 'paragraphs': ['春眠不觉晓，处处闻啼鸟。', '山中兵战起，剑影动秋风。']}], ensure_ascii=False).encode()
        self.assertEqual(list(corpus.extract_entries({'kind': 'poetry'}, raw)),
                         [('春眠不觉晓，处处闻啼鸟。——孟浩然', 0, 0)])

    def test_daily_plan_uses_year_history_and_survives_source_reload_failure(self):
        day = site_day()
        old = '春眠不觉晓，处处闻啼鸟。——孟浩然'
        fresh = '山光悦鸟性，潭影空人心。——常建'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Library(root / settings.DATABASE_NAME)
            before = days_ago(100)
            db.save_daily({'run_id': 'synthetic-old', 'site_day': before,
                           'started_at': before + 'T20:00:00+00:00', 'finished_at': before + 'T20:01:00+00:00',
                           'status': 'complete', 'actions': [{'action': 'checkin', 'status': 'reward_verified',
                                                              'mood': '开心', 'phrase': old}]}, 123456)
            db.close()
            with patch('daily.STATE', root), patch('daily.ACCOUNT_UID', 123456), \
                    patch('daily.CHECKIN_MOOD_RANDOM', True), patch('daily.choose_mood', return_value='开心'), \
                    patch('corpus.JOURNAL_STYLE', 'poetry'), \
                    patch('daily.load_corpus', return_value=[(old, 'poetry'), (fresh, 'poetry')]) as load:
                self.assertEqual(daily._checkin_plan(day)['phrase'], fresh)
                load.side_effect = ValueError('synthetic corruption')
                self.assertEqual(daily._checkin_plan(day)['phrase'], fresh)
                self.assertEqual(load.call_count, 1)
                with patch('daily.CHECKIN_MOOD_RANDOM', False):
                    self.assertIsNone(daily._checkin_plan(day)['phrase'])
                self.assertEqual(load.call_count, 1)


if __name__ == '__main__':
    unittest.main()
