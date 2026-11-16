"""Frozen PyInstaller entry point owned by the Electron desktop process."""
import argparse
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='HMR Desk local engine')
    parser.add_argument('--data-dir')
    parser.add_argument('--workspace')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--version', action='store_true')
    parser.add_argument('--recover-key', action='store_true',
                        help='read a recovery key from standard input and unlock this PC\'s database')
    args = parser.parse_args(argv)
    if args.version:
        print('hmr-engine 0.1.0')
        return 0
    if args.port < 1 or args.port > 65535:
        parser.error('Invalid loopback API port')
    if args.data_dir:
        os.environ['HMR_DATA_DIR'] = os.path.abspath(args.data_dir)
    if args.workspace:
        os.environ['HMR_WORKSPACE'] = os.path.abspath(args.workspace)
    os.environ['HMR_API_PORT'] = str(args.port)
    import app_paths
    app_paths.ensure_writable(app_paths.data_root())
    app_paths.ensure_writable(app_paths.workspace_root())
    if args.recover_key:
        import db, dbkey
        try:
            db.recover_key(sys.stdin.readline())
        except (dbkey.RecoveryKeyError, ValueError, dbkey.KeyUnavailable) as exc:
            print(str(exc), file=sys.stderr)
            return 4
        print('Recovery key accepted. This PC can open the database.')
        return 0
    try:
        import service
        service.main()
    except Exception as exc:
        import dbkey
        if isinstance(exc, dbkey.KeyUnavailable):
            # Exit code 3: the database is encrypted and this PC has no working key (needs the recovery key).
            from pathlib import Path
            (Path(app_paths.data_root()) / 'startup-failure.txt').write_text('dbkey.KeyUnavailable\n', encoding='utf-8')
            return 3
        # Record only exception class, never patient values, raw paths or secrets.
        from pathlib import Path
        failure = Path(app_paths.data_root()) / 'startup-failure.txt'
        failure.write_text(type(exc).__module__ + '.' + type(exc).__name__ + '\\n', encoding='utf-8')
        raise
    return 0


if __name__ == '__main__':
    sys.exit(main())
