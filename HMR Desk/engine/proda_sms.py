"""Ephemeral, local-only PRODA SMS attempts; no message contents are retained."""
import datetime as dt
import os
import re
import secrets
import threading

import outbox

ORIGIN = 'https://proda.humanservices.gov.au'
TTL = dt.timedelta(minutes=5)
INTERVAL = dt.timedelta(seconds=2)
MAX_ATTEMPTS = 32
_lock = threading.Lock()
_attempts = {}
_used = {}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _prune(now):
    for key, value in list(_attempts.items()):
        if now - value['start'] > TTL:
            del _attempts[key]
    for key, expires in list(_used.items()):
        if now >= expires:
            del _used[key]


def _trusted_sender():
    # Local configuration only: never accepted from API requests or settings.
    name = 'HMR_PRODA_VERIFIED_SENDER'
    sender = os.environ.get(name)
    if name not in os.environ:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                sender, value_type = winreg.QueryValueEx(key, name)
            if value_type != winreg.REG_SZ:
                return None
        except (ImportError, OSError):
            return None
    return sender if isinstance(sender, str) and re.fullmatch(r'[A-Za-z0-9+][A-Za-z0-9+ -]{0,62}[A-Za-z0-9+]?', sender) else None


def _code_wording(text):
    return bool(re.search(r'\b(?:verification|verify|login|log[ -]?in|security)\b', text, re.I)
                and re.search(r'\bcode\b', text, re.I))


def start(enabled, body):
    if not enabled:
        return {'status': 'disabled'}
    if not isinstance(body, dict) or set(body) - {'origin'} or ('origin' in body and body['origin'] != ORIGIN):
        return {'status': 'unavailable'}
    sender = _trusted_sender()
    if not sender:
        return {'status': 'unavailable'}
    with _lock:
        now = _now()
        _prune(now)
        if len(_attempts) >= MAX_ATTEMPTS:
            return {'status': 'unavailable'}
        attempt = secrets.token_urlsafe(32)
        _attempts[attempt] = {'start': now, 'last': None, 'done': False, 'sender': sender}
        return {'status': 'started', 'attempt_id': attempt, 'started_at': now.isoformat().replace('+00:00', 'Z')}


def is_proda_code(sender, text):
    """Match PRODA identification and authentication-code wording, including truncated codes."""
    if not isinstance(sender, str) or not isinstance(text, str):
        return False
    # Privacy filtering is deliberately broader than sender authentication for polling.
    return bool(re.search(r'\b(?:otp|pass[ -]?code|one[ -]?time[ -]?(?:code|password|pin))\b', text, re.I)
                or re.search(r'\b(?:verification|verify|login|log[ -]?in|security|authentication|authenticat(?:e|ion))\b', text, re.I)
                and re.search(r'\b(?:code|pin)\b', text, re.I))


def poll(enabled, body):
    if not enabled:
        return {'status': 'disabled'}
    if not isinstance(body, dict) or set(body) != {'attempt_id'} or not isinstance(body['attempt_id'], str):
        return {'status': 'unavailable'}
    with _lock:
        now = _now()
        attempt = _attempts.get(body['attempt_id'])
        if not attempt or now - attempt['start'] > TTL or now < attempt['start']:
            _prune(now)
            return {'status': 'expired'}
        if attempt['done']:
            return {'status': 'expired'}
        if not _trusted_sender() or _trusted_sender() != attempt['sender']:
            return {'status': 'unavailable'}
        if attempt['last'] and now - attempt['last'] < INTERVAL:
            return {'status': 'waiting'}
        attempt['last'] = now
        try:
            since = attempt['start'].strftime('%Y-%m-%dT%H:%M:%SZ')
            items, total = outbox.make_client().get_inbox_page(since, limit=100, offset=0)
            if not isinstance(items, list) or len(items) >= 100 or (total is not None and total > len(items)):
                return {'status': 'unavailable'}
            matches = []
            for item in items:
                if not isinstance(item, dict) or item.get('type') != 'SMS':
                    continue
                sender, text, stamp, msg_id = (item.get(k) for k in ('sender', 'contentPreview', 'createdAt', 'id'))
                if not all(isinstance(x, str) and x for x in (sender, text, stamp, msg_id)):
                    continue
                try:
                    received = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                    if received.tzinfo is None or not attempt['start'] < received <= now:
                        continue
                except (ValueError, TypeError):
                    continue
                # A body mentioning PRODA is useful for privacy filtering, never sender authentication.
                if sender != attempt['sender'] or not _code_wording(text):
                    continue
                numbers = re.findall(r'(?<!\d)\d{6}(?!\d)', text)
                if len(numbers) != 1:
                    return {'status': 'ambiguous'}
                matches.append((msg_id, numbers[0]))
            if len(matches) > 1:
                return {'status': 'ambiguous'}
            if not matches:
                return {'status': 'waiting'}
            msg_id, code = matches[0]
            _prune(now)
            if msg_id in _used:
                return {'status': 'ambiguous'}
            # Bound replay memory without ever evicting a still-live message ID.
            if len(_used) >= 1024:
                return {'status': 'unavailable'}
            _used[msg_id] = now + TTL
            attempt['done'] = True
            return {'status': 'code', 'code': code}
        except Exception:
            return {'status': 'unavailable'}


def finish(body):
    if not isinstance(body, dict) or set(body) != {'attempt_id', 'outcome'} or not isinstance(body['attempt_id'], str) or body['outcome'] not in ('submitted', 'cancelled', 'failed'):
        return {'status': 'unavailable'}
    with _lock:
        _attempts.pop(body['attempt_id'], None)
    return {'status': 'finished'}
