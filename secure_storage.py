"""Authenticated encryption for concern payloads; synthetic transaction fixtures stay clear."""
import json
import hashlib
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from privacy import sanitise, protect

PREFIX = 'enc:v1:'


class StorageSecurityError(ValueError):
    pass


class Codec:
    def __init__(self, database, encrypted_exists=False):
        key = os.environ.get('CONCERN_ENCRYPTION_KEY')
        if not key:
            directory = Path(database).parent / '.private'
            path = directory / 'concerns.key'
            if not path.exists():
                if encrypted_exists:
                    raise StorageSecurityError('Encryption key missing. Restore the original key; data is not overwritten.')
                directory.mkdir(mode=0o700, exist_ok=True)
                os.chmod(directory, 0o700)
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, 'wb') as file:
                        file.write(Fernet.generate_key())
            os.chmod(path, 0o600)
            key = path.read_bytes()
        try:
            self.cipher = Fernet(key)
        except (ValueError, TypeError):
            raise StorageSecurityError('Invalid encryption key configuration.') from None

    def seal(self, text):
        return PREFIX + self.cipher.encrypt(text.encode('utf-8')).decode('ascii')

    def open(self, text):
        if not text.startswith(PREFIX):
            return text  # Legacy input, migrated by the protected connection.
        try:
            return self.cipher.decrypt(text[len(PREFIX):].encode('ascii')).decode('utf-8')
        except (InvalidToken, ValueError, UnicodeError):
            raise StorageSecurityError('Stored payload cannot be authenticated. Restore the correct encryption key.') from None


def migrate(db, codec):
    """Sanitise and seal legacy values atomically; never silently decrypt to disk."""
    tables = {'concerns': [('state_json', True)],
              'concern_events': [('state_json', True), ('customer_statement', False)],
              'handoff_requests': [('summary_json', True)],
              'case_commands': [('payload_json', True)],
              'cases': [('record_json', True)],
              'actions': [('record_json', True)],
              'audit_events': [('record_json', True)]}
    with db:
        for table, columns in tables.items():
            for column, is_json in columns:
                for row in db.execute(f'SELECT rowid,{column} FROM {table} WHERE {column} NOT LIKE ?', (PREFIX + '%',)).fetchall():
                    raw = row[1]
                    clean = json.dumps(sanitise(json.loads(raw)), ensure_ascii=False) if is_json else protect(raw).text
                    if table == 'concern_events' and column == 'state_json':
                        original = json.loads(clean)
                        if 'messages' in original:
                            clean = json.dumps({'state_step': original.get('step'), 'snapshot_digest': hashlib.sha256(clean.encode()).hexdigest()})
                    db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?', (codec.seal(clean), row[0]))
