"""Explicit local-admin retention maintenance; dry-run by default."""
from datetime import datetime, timezone, timedelta
from concerns import connection, audit


def purge_expired(days, database=None, execute=False, now=None):
    if type(days) is not int or days < 1:
        raise ValueError('A positive, explicitly agreed retention period is required.')
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    with connection(database) as db:
        # The write lock keeps a concurrent hold/update from racing the deletion.
        db.execute('BEGIN IMMEDIATE')
        ids = [row[0] for row in db.execute(
            "SELECT concern_id FROM concerns WHERE updated_at<? AND concern_id NOT IN (SELECT concern_id FROM concern_holds) "
            "AND concern_id NOT IN (SELECT concern_id FROM case_links) "
            "AND concern_id NOT IN (SELECT concern_id FROM case_commands WHERE status IN ('SUBMITTING','UNKNOWN','SUCCEEDED')) "
            "AND concern_id NOT IN (SELECT concern_id FROM card_commands WHERE status IN ('SUBMITTING','UNKNOWN','SUCCEEDED'))", (cutoff,))]
        if execute:
            for cid in ids:
                for table in ('card_commands', 'case_commands', 'handoff_requests', 'concern_review', 'concern_events'):
                    db.execute(f'DELETE FROM {table} WHERE concern_id=?', (cid,))
                db.execute('DELETE FROM concerns WHERE concern_id=?', (cid,))
                audit(db, cid, 'local-retention-admin', 'RETENTION_PURGED')
        return {'mode': 'executed' if execute else 'dry_run', 'eligible_concerns': len(ids), 'retention_days': days}


def set_hold(concern_id, reason_code, database=None):
    if reason_code not in ('LEGAL_HOLD', 'INVESTIGATION_HOLD'):
        raise ValueError('Use an approved non-PII hold reason code.')
    with connection(database) as db:
        db.execute('INSERT OR REPLACE INTO concern_holds VALUES (?,?)', (concern_id, reason_code))
