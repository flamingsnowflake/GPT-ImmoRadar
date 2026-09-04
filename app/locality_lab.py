"""In-memory locality navigation; never changes persisted property decisions."""
from datetime import datetime, timezone

from energy_lab_auto import next_energy_action


class LocalityLab:
    def __init__(self):
        self.skipped = set()
        self.session = None

    def reset(self):
        self.skipped.clear()
        self.session = None

    def track(self, message_id, row):
        self.session = None if not message_id or row is None else {
            'message_id': message_id,
            'portal': str(row.get('portal') or '').strip().lower(),
            'portal_id': str(row.get('portal_id') or ''),
            'started_at': datetime.now(timezone.utc).isoformat(),
        }

    def rows(self, rows):
        return [row for row in rows
                if str(row.get('portal_id') or '') not in self.skipped]

    def next_action(self, rows, terminal_status=None):
        rows = self.rows(rows)
        current_id = (self.session or {}).get('portal_id')
        if terminal_status:
            rows = [row for row in rows if str(row.get('portal_id') or '') != current_id]
        action, row = next_energy_action(current_id, rows)
        return action, row, len(rows)
