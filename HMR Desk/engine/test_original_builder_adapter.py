import ast
import json
import tempfile
import unittest
from pathlib import Path

import original_builder_adapter as adapter


def data():
    return {'name': 'Synthetic Testpatient', 'assess_date': '01/01/2026', 'report_date': '02/01/2026',
            'patient': 'p', 'doctor': 'd', 'dear': 'x', 'thanks': 't', 'reason': 'r', 'intro': 'i',
            'conditions': 'c', 'allergies': 'a', 'obs': 'o', 'followup': 'f', 'path_date': '01/12/2025',
            'meds': [['a', 'b', 'c', 'd']], 'otc': [], 'ceased': [], 'path': [],
            'issues': [{'title': 'T', 'rec': 'R', 'rationale': 'Q', 'suggestion_source': {'x': 1}}],
            'followup_decision': 'x', 'interaction_scope_note': 'SYNTHETIC SCOPE NOTE'}


def fake_runner(code=0, write_docx=True, write_pdf=True, leak=None):
    """Stands in for the builder: writes into the staged out path and the redirected temp folder."""
    def run(script, spec_path, scratch):
        spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
        if leak is not None:
            leak.append(Path(spec_path))
        sub = Path(tempfile.mkdtemp(dir=scratch))
        leak is not None and leak.append(sub)
        if write_pdf:
            (sub / 'r.pdf').write_bytes(b'pdf')
        (sub / 'sheet.png').write_bytes(b'png')
        if write_docx:
            Path(spec['out']).write_bytes(b'docx')
        return code
    return run


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 't.docx').write_bytes(b'x')
        (self.root / 'b.py').write_text('#')

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, **kw):
        runner = kw.pop('runner', fake_runner())
        return adapter.build(data(), self.root / 'o.docx', self.root / 't.docx', self.root / 'b.py',
                             runner=runner, fonts=kw.pop('fonts', lambda p: {'Montserrat'}), **kw)

    def test_spec_keys_match_original_required_keys(self):
        spec = adapter.to_spec(data(), 'out.docx', 'tpl.docx')
        tree = ast.parse((Path(__file__).parent / 'jobs.py').read_text(encoding='utf-8'))
        keys = next(ast.literal_eval(n.value) for n in tree.body
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'REPORT_KEYS')
        self.assertEqual(set(spec) - {'template'}, keys)

    def test_internal_fields_dropped_and_scope_note_kept_visible(self):
        spec = adapter.to_spec(data(), 'o.docx', 't.docx')
        self.assertNotIn('followup_decision', spec)
        self.assertEqual(set(spec['issues'][0]), {'title', 'rec', 'rationale'})
        self.assertTrue(spec['intro'].endswith('SYNTHETIC SCOPE NOTE'))

    def test_missing_key_fails(self):
        d = data(); del d['obs']
        with self.assertRaises(ValueError):
            adapter.to_spec(d, 'o.docx', 't.docx')

    def test_success_returns_docx_and_word_pdf_and_cleans_temp(self):
        seen = []
        docx, pdf = self.call(pdf_target=self.root / 'o.pdf', runner=fake_runner(leak=seen))
        self.assertEqual((docx.read_bytes(), pdf.read_bytes()), (b'docx', b'pdf'))
        self.assertTrue(all(not p.exists() for p in seen))

    def test_docx_only_leaves_no_pdf(self):
        docx, pdf = self.call()
        self.assertIsNone(pdf)
        self.assertFalse((self.root / 'o.pdf').exists())

    def test_builder_failure_no_outputs_no_leak_no_text(self):
        seen = []
        with self.assertRaises(RuntimeError) as ctx:
            self.call(pdf_target=self.root / 'o.pdf', runner=fake_runner(code=1, leak=seen))
        self.assertEqual(str(ctx.exception), 'Original report builder failed (exit 1)')
        self.assertTrue(all(not p.exists() for p in seen))
        self.assertFalse((self.root / 'o.docx').exists())

    def test_missing_word_render_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.call(runner=fake_runner(write_pdf=False))
        self.assertFalse((self.root / 'o.docx').exists())

    def test_missing_font_fails_closed_no_outputs(self):
        with self.assertRaises(RuntimeError):
            self.call(pdf_target=self.root / 'o.pdf', fonts=lambda p: {'Arial'})
        self.assertFalse((self.root / 'o.docx').exists() or (self.root / 'o.pdf').exists())

    def test_never_overwrites_either_output(self):
        (self.root / 'o.pdf').write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            self.call(pdf_target=self.root / 'o.pdf')
        self.assertEqual((self.root / 'o.pdf').read_bytes(), b'old')

    def test_concurrent_target_not_clobbered_and_not_deleted(self):
        def racing(script, spec_path, scratch):
            code = fake_runner()(script, spec_path, scratch)
            (self.root / 'o.docx').write_bytes(b'other job')  # appears after our pre-check
            return code
        with self.assertRaises(FileExistsError):
            self.call(runner=racing)
        self.assertEqual((self.root / 'o.docx').read_bytes(), b'other job')

    def test_pdf_race_after_docx_claim_removes_only_ours(self):
        def racing(script, spec_path, scratch):
            code = fake_runner()(script, spec_path, scratch)
            (self.root / 'o.pdf').write_bytes(b'other pdf')
            return code
        with self.assertRaises(FileExistsError):
            self.call(pdf_target=self.root / 'o.pdf', runner=racing)
        self.assertFalse((self.root / 'o.docx').exists())
        self.assertEqual((self.root / 'o.pdf').read_bytes(), b'other pdf')

    def test_worker_main_maps_exit_without_touching_parent_state(self):
        import sys
        argv, out = list(sys.argv), sys.stdout
        script = self.root / 's.py'
        script.write_text("import sys\nsys.exit('private text')\n")
        self.assertEqual(adapter.worker_main([str(script), 'spec.json']), 1)
        script.write_text("assert False\n")
        self.assertEqual(adapter.worker_main([str(script), 'spec.json']), 2)
        script.write_text("raise ValueError('x')\n")
        self.assertEqual(adapter.worker_main([str(script), 'spec.json']), 3)
        sys.argv = argv; self.assertIs(sys.stdout, out)

    def test_real_worker_subprocess_isolated_and_temp_in_scratch(self):
        script = self.root / 'b.py'
        script.write_text("import sys, tempfile, pathlib\n"
                          "spec = __import__('json').load(open(sys.argv[1], encoding='utf-8'))\n"
                          "pathlib.Path(spec['out']).write_bytes(b'docx')\n"
                          "d = tempfile.mkdtemp(); pathlib.Path(d, 'r.pdf').write_bytes(b'pdf')\n")
        before = tempfile.tempdir
        docx, pdf = adapter.build(data(), self.root / 'o.docx', self.root / 't.docx', script,
                                  pdf_target=self.root / 'o.pdf', fonts=lambda p: {'Montserrat'})
        self.assertEqual((docx.read_bytes(), pdf.read_bytes()), (b'docx', b'pdf'))
        self.assertEqual(tempfile.tempdir, before)

    def test_timeout_kills_worker_before_return(self):
        script = self.root / 'slow.py'
        script.write_text("import time\ntime.sleep(60)\n")
        import time
        start = time.monotonic()
        self.assertEqual(adapter.run_worker(script, self.root / 'spec.json', self.root, timeout=1), 4)
        self.assertLess(time.monotonic() - start, 20)


if __name__ == '__main__':
    unittest.main()


class WordNeverKilledTests(unittest.TestCase):
    STARTED = '2026-11-21T01:00:00'
    AUTO_OTHER = ('2026-11-21T01:00:05', '"C:\\Office\\WINWORD.EXE" /Automation -Embedding')  # another program's automation Word
    USER = ('2026-11-21T01:00:06', '"C:\\Office\\WINWORD.EXE" "C:\\Users\\x\\Unrelated.docx"')

    def test_lingering_word_is_only_counted(self):
        table = {10: self.AUTO_OTHER, 20: self.USER, 30: ('2026-11-21T00:00:00', self.AUTO_OTHER[1])}
        n = adapter.lingering_word({30}, self.STARTED, instances=lambda: table, grace=2, sleep=lambda s: None)
        self.assertEqual(n, 1)  # pid 10 only: could be ours or another program's, so it is a hint, not an action
        gone = adapter.lingering_word(set(), self.STARTED, instances=lambda: {20: self.USER}, grace=2, sleep=lambda s: None)
        self.assertEqual(gone, 0)

    def test_unreadable_table_never_raises(self):
        def boom():
            raise OSError('x')
        self.assertEqual(adapter.lingering_word(set(), self.STARTED, instances=boom, sleep=lambda s: None), 0)

    def test_no_function_exists_that_ends_a_word_process(self):
        self.assertFalse(hasattr(adapter, 'reap_owned_word') or hasattr(adapter, '_kill_pid'))
        src = Path(adapter.__file__).read_text(encoding='utf-8')
        self.assertEqual(src.count('taskkill'), 1)  # only kill_tree, aimed at the worker pid
        self.assertNotIn('Stop-Process', src)
        self.assertNotIn('/IM', src)

    def test_timeout_with_concurrent_unrelated_automation_word_ends_only_the_worker(self):
        import subprocess as sp
        ended, spawned = [], []
        real = (adapter.kill_tree, adapter.word_instances, sp.run, adapter.os.kill, adapter.time.sleep)
        table = {77: self.AUTO_OTHER, 88: self.USER}  # another program's automation Word plus a user's Word, both stay
        adapter.kill_tree = lambda child: ended.append(('worker', child.pid))
        adapter.word_instances = lambda: ({} if not spawned else table)
        adapter.time.sleep = lambda s: None
        sp.run = lambda *a, **k: spawned.append(a) or (_ for _ in ()).throw(AssertionError('nothing else may be run'))
        adapter.os.kill = lambda *a: ended.append(('os.kill',) + a)
        try:
            real_popen = sp.Popen

            def popen(*a, **k):
                child = real_popen(*a, **k)
                spawned.append('popen')
                return child
            sp.Popen = popen
            code = adapter.run_worker(Path(adapter.__file__), Path(adapter.__file__), tempfile.gettempdir(), timeout=0.01)
        finally:
            sp.Popen = real_popen
            adapter.kill_tree, adapter.word_instances, sp.run, adapter.os.kill, adapter.time.sleep = real
        self.assertEqual(code, 5)  # warned, not killed
        self.assertEqual([e[0] for e in ended], ['worker'])
        self.assertEqual([x for x in spawned if x != 'popen'], [])

    def test_exit_5_gives_a_fixed_warning_without_report_content(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 't.docx').write_bytes(b'x'); (root / 'b.py').write_text('#')
            with self.assertRaises(RuntimeError) as ctx:
                adapter.build(data(), root / 'o.docx', root / 't.docx', root / 'b.py', runner=lambda *a: 5, fonts=lambda p: {'Montserrat'})
            self.assertIn('not stopped', str(ctx.exception))
            self.assertNotIn('Synthetic', str(ctx.exception))
            self.assertFalse((root / 'o.docx').exists())
