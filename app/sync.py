import contextlib
import json
import os
from pathlib import Path
import time
from core import TencentSource, SourceError, NotStandardMayhem, normalize, scrub, utc_now
from store import Store


@contextlib.contextmanager
def sync_lock(directory):
    path = Path(directory) / 'sync.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SourceError('sync_already_running') from None
    try:
        yield
    finally:
        handle.close()


def run_sync(directory, limit=200, progress=None, source_factory=TencentSource):
    if not 1 <= limit <= 2000:
        raise SourceError('invalid_sync_limit')
    store = Store(directory)
    state = {'running': True, 'started_at': utc_now(), 'completed': 0, 'cached': 0,
             'failed': 0, 'skipped': 0, 'scanned': 0, 'requested_limit': limit,
             'source': '腾讯 SGP V3', 'listing_end': 'not_reached', 'last_error': None}
    def update():
        state['updated_at'] = utc_now()
        store.set('sync_status', state)
        if progress:
            progress(dict(state))
    with sync_lock(directory):
        update()
        try:
            source = source_factory()
            account = store.register(source)
            raw_dir = Path(directory) / 'raw'
            raw_dir.mkdir(exist_ok=True)
            ids, seen = [], set()
            while len(ids) < limit:
                count = min(200, limit - len(ids))
                page = source.list_ids(len(ids), count)
                new = [mid for mid in page if mid not in seen]
                if page and not new:
                    state['listing_end'] = 'repeated_page'
                    break
                ids.extend(new[:count])
                seen.update(new)
                store.discover(account['account_key'], new[:count])
                state['scanned'] = len(ids)
                update()
                if len(page) < count:
                    state['listing_end'] = 'available_window_end'
                    break
            if len(ids) >= limit:
                state['listing_end'] = 'requested_limit'
            for index, mid in enumerate(ids):
                state['processed'] = index + 1
                if store.has(account['account_key'], mid):
                    state['cached'] += 1
                    update()
                    continue
                try:
                    path = raw_dir / (mid + '.json')
                    raw = None
                    if path.exists():
                        try:
                            raw = json.loads(path.read_text(encoding='utf-8'))
                        except (OSError, ValueError):
                            pass
                    if not isinstance(raw, dict):
                        raw = source.summary(mid)
                    match = normalize(raw, account['puuid'], expected_id=mid)
                    store.save_payload(mid, 'summary', 'sgp_v3_summary', raw)
                    # Save only validated target matches, and never authentication material.
                    text = json.dumps(scrub(raw), ensure_ascii=False, indent=2)
                    temporary = raw_dir / (mid + '.json.tmp')
                    temporary.write_text(text, encoding='utf-8')
                    temporary.replace(path)
                    store.put(account['account_key'], match)
                    state['completed'] += 1
                except NotStandardMayhem:
                    store.discovery_status(account['account_key'], mid, 'skipped', 'non_standard_queue')
                    state['skipped'] += 1
                except SourceError as error:
                    if error.code in ('login_token_unavailable', 'local_connection_failed', 'local_request_failed'):
                        raise
                    store.discovery_status(account['account_key'], mid, 'failed', str(error))
                    state['last_error'] = str(error)
                    state['failed'] += 1
                update()
            state['outcome'] = 'completed_with_gaps' if state['failed'] else 'completed_requested_window'
        except SourceError as error:
            state['last_error'] = str(error)
            state['outcome'] = 'source_unavailable'
        except Exception as error:
            # Only the exception class is retained; tracebacks can disclose credentials.
            state['last_error'] = type(error).__name__
            state['outcome'] = 'local_error'
        finally:
            state['running'] = False
            state['finished_at'] = utc_now()
            update()
        try:
            from public_site import push_public_snapshot
            push_public_snapshot(directory)
        except Exception:
            pass  # Public delivery must never change a completed collection outcome.
    return state
