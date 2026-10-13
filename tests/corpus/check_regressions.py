#!/usr/bin/env python3
"""Assert fixed fidelity defects in a completed `evaluate --reference` run."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

EVALUATION = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else None
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class FidelityRegressions(unittest.TestCase):
    def job(self, fixture_id):
        self.assertIsNotNone(EVALUATION, 'Pass the corpus evaluation directory')
        results = json.loads((EVALUATION / 'results.json').read_text())
        fixture = next((f for f in results['fixtures'] if f['id'] == fixture_id), None)
        self.assertIsNotNone(fixture, f'Missing fixture: {fixture_id}')
        self.assertEqual(fixture['status'], 'converted')
        return EVALUATION / fixture_id, fixture

    def test_doc_image_in_worddocument_stream(self):
        job, _ = self.job('poi-word-PngPicture-doc')
        # Exact original PNG bytes, not merely a new media part or placeholder.
        with zipfile.ZipFile(job / 'normalization/normalized.docx') as docx:
            hashes = {hashlib.sha256(docx.read(n)).hexdigest()
                      for n in docx.namelist() if n.startswith('word/media/')}
        self.assertIn('c7ed7eaee12184fbae328aec72e7448b65c46296dbb04eae90e0bac9e0de9f32', hashes)
        for stage, name in [('davros', 'preview'), ('normalized_reference', 'input')]:
            listing = subprocess.check_output(
                ['pdfimages', '-list', job / stage / (name + '.pdf')], text=True)
            self.assertTrue(any('image' in line.split() for line in listing.splitlines()[2:]), listing)

    def test_doc_explicit_page_break_and_distinct_headers(self):
        job, result = self.job('poi-word-DiffFirstPageHeadFoot-doc')
        with zipfile.ZipFile(job / 'normalization/normalized.docx') as docx:
            document = ET.fromstring(docx.read('word/document.xml'))
        breaks = [b for b in document.iter(W + 'br') if b.get(W + 'type') == 'page']
        self.assertEqual(len(breaks), 1)
        for stage, name in [('davros', 'preview'), ('normalized_reference', 'input')]:
            self.assertEqual(result[stage]['pdf']['pages'], 2)
            pages = (job / stage / (name + '.txt')).read_text().split('\f')
            self.assertIn('header on the first page', pages[0])
            self.assertIn('footer of the first page', pages[0])
            self.assertIn('End of page 1', pages[0])
            self.assertNotIn('This is page two', pages[0])
            self.assertIn('This is page two', pages[1])
            self.assertIn('First header column!', pages[1])
            self.assertIn('Footer Right', pages[1])
            self.assertNotIn('header on the first page', pages[1])

    def test_doc_automatic_notes_have_matching_references_and_visible_bodies(self):
        job, _ = self.job('poi-word-footnote-doc')
        with zipfile.ZipFile(job / 'normalization/normalized.docx') as docx:
            main = ET.fromstring(docx.read('word/document.xml'))
            for kind, text in [('footnote', 'TestFootnote'), ('endnote', 'TestEndnote')]:
                refs = [r.get(W + 'id') for r in main.iter(W + kind + 'Reference')]
                self.assertEqual(refs, ['1'])
                root = ET.fromstring(docx.read('word/' + kind + 's.xml'))
                notes = [n for n in root if n.get(W + 'id') == refs[0]]
                self.assertEqual(len(notes), 1)
                self.assertIn(text, ''.join(notes[0].itertext()))
                self.assertIsNotNone(notes[0].find('.//' + W + kind + 'Ref'))
        for stage, name in [('davros', 'preview'), ('normalized_reference', 'input')]:
            text = (job / stage / (name + '.txt')).read_text()
            self.assertIn('TestFootnote', text)
            self.assertIn('TestEndnote', text)
            self.assertNotIn('TestComment', text)

    def test_doc_png_keeps_natural_aspect_ratio(self):
        job, _ = self.job('poi-word-PngPicture-doc')
        with zipfile.ZipFile(job / 'normalization/normalized.docx') as docx:
            root = ET.fromstring(docx.read('word/document.xml'))
        extents = root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent')
        self.assertEqual(len(extents), 1)
        self.assertFalse(any(style.get(W + 'val', '').startswith('Heading')
                             for style in root.iter(W + 'pStyle')))
        self.assertEqual(int(extents[0].get('cx')) * 55, int(extents[0].get('cy')) * 189)

    def test_xls_dates_retain_distinct_formats(self):
        job, _ = self.job('poi-excel-DateFormats-xls')
        for stage, name in [('davros', 'preview'), ('normalized_reference', 'input')]:
            text = (job / stage / (name + '.txt')).read_text()
            for date in ['10-Aug-07', '8/10/07', '10/08/07']:
                self.assertIn(date, text)
            self.assertNotIn('2007-08-10', text)

    def test_ppt_untitled_slide_has_no_invented_title(self):
        job, _ = self.job('poi-powerpoint-text-margins-ppt')
        for stage, name in [('davros', 'preview'), ('normalized_reference', 'input')]:
            text = (job / stage / (name + '.txt')).read_text()
            for label in ['TEST1', 'TEST2', 'TEST3', 'TEST4']:
                self.assertIn(label, text)
            self.assertNotIn('Slide 1', text)


if __name__ == '__main__':
    unittest.main()
