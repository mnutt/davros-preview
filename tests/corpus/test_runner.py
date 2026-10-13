"""Tests for corpus accounting; no network, reference suite, or renderer needed."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

import run


class RunnerTests(unittest.TestCase):
    def test_duplicate_ids_cannot_overwrite_legacy_modern_pairs(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate fixture id'):
            run.validate_manifest({'fixtures': [{'id': 'same'}, {'id': 'same'}]})

    def test_pinned_file_rejects_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'fixture'
            p.write_bytes(b'good')
            record = {'sha256': hashlib.sha256(b'good').hexdigest(), 'size': 4}
            run.verified(p, record)
            p.write_bytes(b'evil')
            with self.assertRaises(ValueError):
                run.verified(p, record)

    def test_text_recall_counts_repeated_missing_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            actual, reference = Path(tmp) / 'actual.pdf', Path(tmp) / 'reference.pdf'
            actual.with_suffix('.txt').write_text('B A extra')
            reference.with_suffix('.txt').write_text('A A B C')
            result = run.compare(actual, reference)
            self.assertEqual(result['token_recall'], 0.5)
            self.assertEqual(result['token_precision'], 0.6667)
            reference.with_suffix('.txt').write_text('')
            self.assertIsNone(run.compare(actual, reference)['token_recall'])

    def test_exit_status_and_per_process_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run.run([sys.executable, '-c', 'raise SystemExit(7)'], Path(tmp), 5)
            self.assertEqual(result['exit_code'], 7)
            self.assertFalse(result['timeout'])
            self.assertGreater(result['peak_rss_mib'], 0)

    def test_timeout_is_not_an_expected_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run.run([sys.executable, '-c', 'import time; time.sleep(5)'], Path(tmp), 0.1)
            self.assertTrue(result['timeout'])
            self.assertLess(result['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
