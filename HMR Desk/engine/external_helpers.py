"""Optional external helper scripts, loaded once. A missing proprietary helper never stops the manual offline app.

Moved verbatim from api.py: helper() loads a helper script up to its data assignment; MIMS_PATH, claims_helper,
mims and record are the loaded optional integrations (mims falls back to the application's own name normaliser).
"""
import ast
import importlib.util

import app_paths
import manual_medicine_names


def helper(filename, stop):
    path = app_paths.resource_root() / filename
    if not path.is_file(): return None
    spec = importlib.util.spec_from_file_location('hmr_' + path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    tree.body = tree.body[:next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign) and any(isinstance(t, (ast.Name, ast.Tuple)) and (getattr(t, 'id', None) in stop or any(getattr(e, 'id', None) in stop for e in getattr(t, 'elts', []))) for t in node.targets))]
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


MIMS_PATH = app_paths.resource_root() / 'MIMS Interaction Helper' / 'make-lists.py'
claims_helper = helper('PPA Claim Helper/make-claims.py', {'claims'})
mims = helper('MIMS Interaction Helper/make-lists.py', {'lists'}) or manual_medicine_names
# External portal scripts are optional. A missing proprietary/unsupported
# helper must NEVER stop the entirely manual, offline clinical HMR application.
_record_path = app_paths.resource_root() / 'PPA Claim Helper' / 'record_report.py'
record = None
if _record_path.is_file():
    _record_spec = importlib.util.spec_from_file_location('hmr_record', _record_path)
    record = importlib.util.module_from_spec(_record_spec)
    _record_spec.loader.exec_module(record)
