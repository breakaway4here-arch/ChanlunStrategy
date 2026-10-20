"""Small durable scheduler for the existing bounded daily maintenance call."""
import fcntl
import json
import math
import os
import tempfile
from pathlib import Path


class RepairQueueError(ValueError):
    pass


class DailyRepairQueue:
    def __init__(self, database, budget=None):
        self.budget = budget
        self.path = Path(str(database) + '.daily-repair.json')
        self.lock_path = Path(str(database) + '.daily-repair.lock')
        self.lock = None
        self.state = {'version': 1, 'sequence': 0, 'entries': {}}

    def __enter__(self):
        self._check_budget()
        try:
            self.lock = self.lock_path.open('a+')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.close()
            raise RepairQueueError('repair_queue_locked') from exc
        try:
            if self.path.exists():
                self.state = json.loads(self.path.read_text())
                if (self.state.get('version') != 1 or not isinstance(self.state.get('entries'), dict)
                        or type(self.state.get('sequence')) is not int
                        or self.state['sequence'] < 0):
                    raise ValueError('invalid queue header')
                for entry in self.state['entries'].values():
                    if (not isinstance(entry, dict) or not isinstance(entry.get('signature'), str)
                            or entry.get('status') not in ('pending', 'inflight', 'failed', 'repaired')
                            or type(entry.get('sequence')) is not int
                            or 'next_attempt' not in entry
                            or not isinstance(entry.get('reasons'), list)
                            or not all(isinstance(reason, str) for reason in entry['reasons'])
                            or not math.isfinite(float(entry['next_attempt']))):
                        raise ValueError('invalid queue entry')
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.close()
            raise RepairQueueError('repair_queue_state_invalid') from exc
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def _check_budget(self):
        if self.budget is not None:
            try:
                self.budget.ensure()
            except ValueError as exc:
                raise RepairQueueError(str(exc)) from exc

    def save(self):
        self._check_budget()
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=self.path.name+'.', dir=str(self.path.parent))
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
                self._check_budget()
                stream.flush()
                self._check_budget()
                os.fsync(stream.fileno())
            self._check_budget()
            os.replace(temporary, self.path)
            temporary = None
            self._check_budget()
            directory = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                self._check_budget()
                os.fsync(directory)
            finally:
                os.close(directory)
        except RepairQueueError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise RepairQueueError('repair_queue_persist_failed') from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def reconcile(self, targets):
        entries = self.state['entries']
        active = {target['key'] for target in targets}
        for key in list(entries):
            if key not in active:
                del entries[key]
        for target in targets:
            old = entries.get(target['key'])
            if old is None or old['signature'] != target['signature']:
                entries[target['key']] = dict(signature=target['signature'], status='pending',
                    sequence=0, next_attempt=0, bad_dates=target['nonfinal_dates'], reasons=[])
        self.save()

    def intent(self, key, source, now):
        self.state['sequence'] += 1
        self.state['entries'][key].update(status='inflight', source=source,
            last_attempt=now, sequence=self.state['sequence'], next_attempt=0)
        # A crash after this write leaves an unknown dispatch, never an automatic retry.
        self.save()

    def finish(self, key, repaired, reasons, now):
        self.state['entries'][key].update(status='repaired' if repaired else 'failed',
            reasons=list(reasons), next_attempt=0 if repaired else now + 6*3600)
        self.save()
