"""Adapter for the owner's original first-app report builder (build.py), kept unmodified.

The reviewed report data already uses the same keys as the original builder's spec, so this module only
selects those keys, keeps the interaction-scope warning visible, writes the spec to a private temporary
folder, runs the original script and removes every temporary file afterwards. It never renders a layout
itself and never falls back to LibreOffice or another renderer: any failure is raised for the caller to show.

Requirements on the PC: Microsoft Word, python-docx, PyMuPDF and the Montserrat font.

Execution: the original is run in this process with runpy, never as `sys.executable script`, because in the
frozen engine sys.executable is hmr-engine.exe, which would parse the script path as its own arguments.

PDF ownership: the original renders a Word PDF into a temporary folder only to check pagination. When a PDF is
wanted, that Word PDF is the one handed back; the caller must not regenerate it with the bundled converter.

Errors carry only fixed text or an exit code: the builder's own messages can contain report content.
"""
import contextlib
import hashlib
import json
import os
import runpy
import shutil
import sys
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SPEC_KEYS = ('name', 'assess_date', 'report_date', 'patient', 'doctor', 'dear', 'thanks', 'reason', 'intro',
             'conditions', 'allergies', 'obs', 'meds', 'otc', 'ceased', 'issues', 'path_date', 'path', 'followup')
ISSUE_KEYS = ('title', 'rec', 'rationale')
REQUIRED_FONT = 'Montserrat'


def to_spec(data, out, template):
    """Reviewed report data to the original builder's spec. Unknown keys are dropped, missing ones fail."""
    missing = [k for k in SPEC_KEYS if k not in data]
    if missing:
        raise ValueError('Report data missing keys for the original builder: ' + ', '.join(missing))
    spec = {k: data[k] for k in SPEC_KEYS}
    note = data.get('interaction_scope_note', '')
    if isinstance(note, str) and note.strip():
        spec['intro'] = (spec['intro'].rstrip() + '\n\n' if spec['intro'].strip() else '') + note
    spec['issues'] = [{k: i[k] for k in ISSUE_KEYS} for i in data['issues']]
    spec['out'] = str(out)
    spec['template'] = str(template)
    return spec


def worker_main(argv):
    """Entry point of the isolated worker process: `<script> <spec>`. Runs the unmodified builder with runpy.

    Only ever called in a child process started by build(), so argv, stdout and the temp folder it touches
    belong to that child alone and no other engine job can see them."""
    if len(argv) != 2:
        return 6
    script, spec = argv
    # The bundled engine exposes this worker switch as a local CLI. A manually
    # invoked frozen engine must not run an arbitrary Python file through runpy.
    # Parent-side checks alone do not protect that invocation.
    if getattr(sys, 'frozen', False):
        try:
            root = Path(script).resolve(strict=True).parent
            if Path(script).is_symlink() or Path(script).name != 'build.py':
                return 6
            for name, digest in PINNED.items():
                asset = root / name
                if asset.is_symlink() or not asset.is_file():
                    return 6
                if hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
                    return 6
            if not Path(spec).is_file():
                return 6
        except (OSError, ValueError):
            return 6
    sys.argv = [script, spec]
    try:
        runpy.run_path(script, run_name='__main__')
        return 0
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 1
    except AssertionError:
        return 2  # the builder's own layout assertion failed
    except Exception:
        return 3


def run_worker(script, spec_path, scratch, timeout=600):
    """Start the isolated worker. Frozen engine: the engine exe with --original-builder-worker, since
    sys.executable there is hmr-engine.exe and cannot run a loose script. Source checkout: this module."""
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, '--original-builder-worker', str(script), str(spec_path)]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve()), str(script), str(spec_path)]
    env = {**os.environ, 'TEMP': str(scratch), 'TMP': str(scratch), 'TMPDIR': str(scratch),
           'PYTHONIOENCODING': 'utf-8'}
    before = set(word_instances())
    started = _utc_stamp(timedelta(seconds=-2))
    try:
        child = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    except OSError:
        return 4
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(child)
        return 5 if lingering_word(before, started) else 4


def kill_tree(child):
    """Stop the worker and what it started (PowerShell) before the caller removes the private folder.
    A Word started through COM is a separate process and is deliberately NOT ended: see lingering_word."""
    if os.name == 'nt':
        with contextlib.suppress(OSError):
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(child.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    with contextlib.suppress(OSError):
        child.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=30)


def _utc_stamp(delta=timedelta(0)):
    return (datetime.now(timezone.utc) + delta).strftime('%Y-%m-%dT%H:%M:%S')


def word_instances():
    """{pid: (utc_creation 'YYYY-MM-DDTHH:MM:SS', command_line)} of every running WINWORD.EXE, read only.
    Empty off Windows or when the query fails (then nothing is ever terminated)."""
    if os.name != 'nt':
        return {}
    script = ("Get-CimInstance Win32_Process -Filter \"Name='WINWORD.EXE'\" | Select-Object ProcessId,CommandLine,"
              "@{n='C';e={$_.CreationDate.ToUniversalTime().ToString('s')}} | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command', script], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=30, text=True).stdout.strip()
        rows = json.loads(out) if out else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    rows = [rows] if isinstance(rows, dict) else rows
    return {int(r['ProcessId']): (str(r.get('C') or '')[:19], str(r.get('CommandLine') or ''))
            for r in rows if isinstance(r, dict) and r.get('ProcessId')}


def lingering_word(before, started, instances=None, grace=10, sleep=None):
    """Observation only, never an action. After a timed-out build, report whether Word processes that
    appeared since the worker started (created later, launched by automation) are still running after a
    short wait. This is a hint for the user's warning, NOT proof they belong to this build: Word runs as a
    separate COM server and nothing in the original scripts gives this module a handle to it, so no Word
    process is ever ended here. Returns the count seen at the end. Never raises."""
    instances = instances or word_instances
    sleep = sleep or time.sleep
    try:
        for _ in range(grace + 1):
            seen = [pid for pid, info in instances().items()
                    if pid not in before and info[0] >= started and '-embedding' in info[1].lower()]
            if not seen:
                return 0
            sleep(1)
        return len(seen)
    except Exception:
        return 0


def claim(source, target):
    """Publish a complete report atomically and without ever overwriting a target.

    The worker output is often under TEMP on another volume. A direct hard
    link is preferable, but EXDEV needs a fully synced sibling temporary file
    *inside the destination directory*, followed by a no-clobber hard link.
    Never stream directly to the clinical report's final filename: an I/O
    failure there would leave an apparently finished, truncated report.
    Filesystems without hard-link support fail closed.
    """
    source, target = Path(source), Path(target)
    try:
        os.link(source, target)
        return
    except FileExistsError:
        raise
    except OSError:
        pass
    fd, scratch = tempfile.mkstemp(prefix='.hmr-report-publish-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.link(scratch, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(scratch)


def _fonts(pdf):
    import fitz
    with fitz.open(str(pdf)) as doc:
        return {f[3] for page in doc for f in page.get_fonts()}


def build(data, target, template, script, pdf_target=None, runner=None, fonts=None):
    """Build one report with the original builder. Neither output may exist already.

    Returns (docx_path, pdf_path_or_None). On any failure no output is left behind."""
    runner = runner or run_worker
    fonts = fonts or _fonts
    target, template, script = Path(target), Path(template), Path(script)
    pdf_target = Path(pdf_target) if pdf_target else None
    for path in (target, pdf_target):
        if path is not None and path.exists():
            raise FileExistsError('Never overwrite existing or signed HMR report')
    for path, what in ((template, 'template'), (script, 'builder')):
        if not path.is_file():
            raise FileNotFoundError('Original report ' + what + ' unavailable')
    work = Path(tempfile.mkdtemp(prefix='.hmr-orig-'))
    made = []
    try:
        scratch = work / 'tmp'
        scratch.mkdir()
        staged = work / 'out' / target.name
        staged.parent.mkdir()
        spec_path = work / 'spec.json'
        spec_path.write_text(json.dumps(to_spec(data, staged, template), ensure_ascii=False), encoding='utf-8')
        code = runner(script, spec_path, scratch)
        if code:
            if code == 5:
                raise RuntimeError('Original report builder timed out. A background Word process may still be running; '
                                   'it was not stopped because it cannot be tied to this build. If it stays, '
                                   'close it in Task Manager, then try again.')
            raise RuntimeError('Original report builder failed (exit ' + str(code) + ')')
        if not staged.is_file():
            raise RuntimeError('Original report builder produced no file')
        word_pdfs = sorted(scratch.rglob('r.pdf'))
        if len(word_pdfs) != 1:
            raise RuntimeError('Original report builder produced no Word render')
        if REQUIRED_FONT not in fonts(word_pdfs[0]):
            raise RuntimeError('Required report font ' + REQUIRED_FONT + ' is not embedded in the Word render')
        target.parent.mkdir(parents=True, exist_ok=True)
        claim(staged, target)  # raises FileExistsError if anything is there; only our own claims are undone
        made.append(target)
        if pdf_target is not None:
            claim(word_pdfs[0], pdf_target)
            made.append(pdf_target)
        return target, pdf_target
    except BaseException:
        for path in made:  # only files this job created
            with contextlib.suppress(OSError):
                path.unlink()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

# The only builder and template this module will run. Pinned here, not in a setting: settings are writable
# through the local HTTP API, so a path or hash held there could point the worker at other code. The files
# stay private; only their SHA-256 values are in source.
ASSET_DIR_NAME = 'original-report-builder'
PINNED = {
    'build.py': '1df5e6820103f6c2503ba9718a679f383d9501630bb63c140f33cd5eccd382d0',
    'Template - Copy.docx': 'c06f10211d7a07c9a0e6190ea4ab603b25c0b83f6bd6d5baf09be15ee9b83edd',
    # build.py renders through the Word helper that sits next to it; it must be present and pinned too.
    'word2pdf.ps1': '3bdcda64efce26c5dfeebd51a0861fe8546009397197f50e42da5a6fa179a7ba',
}


def asset_dir(data_dir):
    return Path(data_dir) / ASSET_DIR_NAME


def assets_present(data_dir):
    """True when the owner has placed the private folder. Absent folder = feature off; a folder with
    wrong or missing files is NOT off: build_with_assets raises, so a bad install never falls back."""
    return asset_dir(data_dir).is_dir()


def build_with_assets(data, target, data_dir, pdf_target=None, **kwargs):
    """Copy the two pinned files into a private folder, hash the COPIES, then build from the copies, so
    what is hashed is what runs. Returns (docx, pdf_or_None, template_sha256)."""
    source = asset_dir(data_dir)
    work = Path(tempfile.mkdtemp(prefix='.hmr-orig-assets-'))
    try:
        copies = {}
        for name, expected in PINNED.items():
            origin = source / name
            if origin.is_symlink() or not origin.is_file():
                raise FileNotFoundError('Original report assets are incomplete')
            copy = work / name
            shutil.copyfile(origin, copy)
            if hashlib.sha256(copy.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Original report assets do not match the recorded files')
            copies[name] = copy
        docx, pdf = build(data, target, copies['Template - Copy.docx'], copies['build.py'], pdf_target, **kwargs)
        return docx, pdf, PINNED['Template - Copy.docx']
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(worker_main(sys.argv[1:]))
