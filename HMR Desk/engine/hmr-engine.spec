# PyInstaller onedir specification; build from HMR Desk/engine on Windows x64.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

sqlcipher_datas, sqlcipher_binaries, sqlcipher_hidden = collect_all('sqlcipher3')

root = Path(SPECPATH)
assets = root / 'assets'
datas = [(str(assets), 'assets')] if assets.is_dir() else []
# Application-owned mapping, not a licensed clinical corpus.
datas.append((str(root / 'drug_classes.json'), '.'))
# Include the legacy parser as a bundled application-owned resource until it is
# completely replaced by local modules. The frozen runtime never uses a Python script path.
legacy = root.parent.parent / 'scripts' / 'intake'
if (legacy / 'intake.py').is_file():
    datas.append((str(legacy), 'scripts/intake'))
for source in ('Android_SMS_Integration', 'MIMS Interaction Helper', 'PPA Claim Helper'):
    own = root.parent.parent / source
    if own.is_dir():
        datas.append((str(own), source))

a = Analysis(
    [str(root / 'engine_main.py')],
    pathex=[str(root)],
    binaries=sqlcipher_binaries,
    datas=datas + collect_data_files('medicine_data') + sqlcipher_datas,
    hiddenimports=collect_submodules('fitz') + collect_submodules('medicine_data') + sqlcipher_hidden,
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
