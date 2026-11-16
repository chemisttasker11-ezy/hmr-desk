#!/usr/bin/env python3
"""Offline medicine reference CLI. Run from any working directory."""
import argparse
import json
from pathlib import Path
import sys

ENGINE = Path(__file__).resolve().parents[2] / 'HMR Desk' / 'engine'
sys.path.insert(0, str(ENGINE))
from medicine_data import amt, artg, catalog, pbs, sigs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('amt', 'pbs', 'artg'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--input', type=Path, required=True)
        cmd.add_argument('--db', type=Path, required=True)
        cmd.add_argument('--release', required=True)
        cmd.add_argument('--source-url', required=True)
        if name == 'amt':
            cmd.add_argument('--accept-ncts-licence', action='store_true',
                             help='Operator confirms a valid NCTS licence for this use')
        if name == 'artg':
            cmd.add_argument('--column-map', type=Path,
                             help='JSON map of logical field -> actual CSV header')
    cmd = sub.add_parser('search')
    cmd.add_argument('--db', type=Path, required=True)
    cmd.add_argument('--text', required=True)
    cmd = sub.add_parser('sig')
    cmd.add_argument('--text', required=True)
    args = parser.parse_args(argv)
    if args.command == 'sig':
        print(json.dumps(sigs.parse(args.text), ensure_ascii=False, indent=2))
        return
    if args.command == 'amt' and not args.accept_ncts_licence:
        parser.error('AMT requires your valid NCTS licence; pass --accept-ncts-licence only after acceptance')
    if args.command == 'search' and not args.db.is_file():
        parser.error('Reference database does not exist; import a source first')
    if args.command != 'search' and not args.input.is_file():
        parser.error('Input file does not exist')
    db = catalog.connect(args.db)
    try:
        if args.command == 'search':
            print(json.dumps(catalog.search(db, args.text), ensure_ascii=False, indent=2))
        elif args.command == 'artg':
            mapping = json.loads(args.column_map.read_text(encoding='utf-8')) if args.column_map else None
            artg.load(db, args.input, args.release, args.source_url, mapping)
        else:
            globals()[args.command].load(db, args.input, args.release, args.source_url)
        if args.command != 'search':
            print(json.dumps(dict(zip(('source', 'release', 'imported_at', 'sha256', 'source_url', 'row_count'),
                               db.execute('SELECT * FROM source_release WHERE source=?', (args.command,)).fetchone())), indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
