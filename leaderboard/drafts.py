"""Bounded, short-lived private handoffs across OAuth browser/storage contexts."""
import json
import secrets
import threading
import time

from fastapi import HTTPException


class DraftHandoffs:
    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def put(self, data):
        raw = json.dumps(data).encode()
        with self._lock:
            now = time.time()
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            if len(self._items) >= 100 or sum(len(v[1]) for v in self._items.values()) + len(raw) > 200 * 1024 * 1024:
                raise HTTPException(503, 'Draft handoff is busy. Your files are still here; please try sign-in again shortly.')
            token = secrets.token_urlsafe(32)
            self._items[token] = (now + 3600, raw)
            return token

    def get(self, token):
        with self._lock:
            item = self._items.get(token)
            if not item or item[0] <= time.time():
                self._items.pop(token, None)
                raise HTTPException(410, 'This sign-in draft has expired. Return to your original submission tab to continue.')
            return json.loads(item[1])
