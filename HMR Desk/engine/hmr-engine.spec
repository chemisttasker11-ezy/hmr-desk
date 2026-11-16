# PyInstaller onedir specification; build from HMR Desk/engine on Windows x64.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
assets = root / 'assets'
datas = [(str(assets), 'assets')] if assets.is_dir() else []
# Include the legacy parser as a bundled application-owned resource until it is
# completely replaced by local modules. The frozen runtime never uses a Python script path.
legacy = root.parent.parent / 'scripts' / 'intake' / 'intake.py'
if legacy.is_file():
    datas.append((str(legacy), 'scripts/intake'))

a = Analysis(
    [str(root / 'engine_main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules('fitz'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='hmr-engine',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='hmr-engine')
