"""Runtime resource and writable workspace locations for source and frozen builds."""
import os
import sys
from pathlib import Path


def resource_root():
    """Installed assets are read-only; never write patient data here."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS).resolve()
    # Source checkout root includes bundled application-owned helpers/scripts.
    return Path(__file__).resolve().parents[2]


def data_root():
    explicit = os.environ.get('HMR_DATA_DIR')
    if explicit:
        return Path(explicit).expanduser().resolve()
    home = Path.home()
    return (home / 'HMR-Desk-data').resolve()


def workspace_root():
    explicit = os.environ.get('HMR_WORKSPACE')
    if explicit:
        return Path(explicit).expanduser().resolve()
    return data_root() / 'workspace'


def ensure_writable(path):
    """Check write permissions using a real create/delete, not os.access alone."""
    import tempfile
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, prefix='.hmr-write-check-', delete=True) as out:
        out.write(b'ok')
        out.flush()
        os.fsync(out.fileno())
    return path


def engine_assets():
    if getattr(sys, 'frozen', False): return resource_root() / 'assets'
    return Path(__file__).resolve().parent / 'assets'
