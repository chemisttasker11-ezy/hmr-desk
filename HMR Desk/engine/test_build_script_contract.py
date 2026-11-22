"""Static checks on the Windows build scripts. They are not a PowerShell run; the Windows build is the real test."""
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def _text(name):
    return (SCRIPTS / name).read_text(encoding='utf-8')


def test_no_script_uses_doubled_path_separators():
    # PowerShell single-quoted strings keep backslashes literally, so '\\' is two separators, not one.
    for script in SCRIPTS.glob('*.ps1'):
        assert '\\\\' not in script.read_text(encoding='utf-8'), script.name


def test_build_script_has_no_host_specific_path_and_uses_one_venv_python():
    text = _text('build-windows.ps1')
    assert not re.search(r"[A-Za-z]:\\", text), 'hard-coded drive path'
    assert text.count("'.venv\\Scripts\\python.exe'") == 1 and text.count('$venvPython @(') >= 2


def test_build_python_is_configurable_and_fails_with_an_actionable_message():
    text = _text('build-windows.ps1')
    assert '$env:HMR_PYTHON' in text
    assert "py', '-3.12'" in text and "'python3.12'" in text
    assert 'Python 3.12 was not found' in text and 'HMR_PYTHON' in text.split('Python 3.12 was not found')[1].split('\n')[0]


def test_build_native_calls_check_exit_codes_one_call_at_a_time_without_a_blanket_continue():
    text = '\n'.join(l for l in _text('build-windows.ps1').splitlines() if not l.lstrip().startswith('#'))
    assert text.count("$ErrorActionPreference = 'Stop'") == 1
    # The preference is relaxed only inside the two native wrappers and restored in a finally block.
    assert text.count("$ErrorActionPreference = 'Continue'") == 2 and text.count('finally { $ErrorActionPreference = $old }') == 2
    for what in ('Python dependencies', 'Engine packaging', 'npm ci', 'Desktop tests', 'NSIS build', 'Creating the build virtual environment'):
        assert "Invoke-Native '%s'" % what in text
    assert 'throw "$What failed (exit code $code)"' in text


def test_python_version_probe_has_no_embedded_double_quotes():
    # Windows PowerShell 5.1 drops double quotes inside a native command argument, which broke the old probe.
    probe = [l for l in _text('build-windows.ps1').splitlines() if "'-c'" in l]
    assert len(probe) == 1
    code = probe[0].split("'-c', ", 1)[1].rsplit("'", 1)[0]
    assert '"' not in code and code.startswith("'import sys")
