"""Run local privacy migration or an explicitly configured retention operation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concerns import connection, DEFAULT_DB
from retention import purge_expired, set_hold

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DB)
    parser.add_argument('--retention-days', type=int)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--hold-concern')
    args = parser.parse_args()
    if args.hold_concern:
        set_hold(args.hold_concern, 'LEGAL_HOLD', args.database)
        print('Preservation hold recorded.')
    elif args.retention_days is not None:
        print(json.dumps(purge_expired(args.retention_days, args.database, execute=args.execute)))
    elif args.execute:
        parser.error('--execute requires --retention-days')
    else:
        with connection(args.database):
            pass
        print('Privacy migration completed; no retention deletion requested.')
