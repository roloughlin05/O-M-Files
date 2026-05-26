#!/usr/bin/env python3
"""
Onshape Duplicate Cleaner
--------------------------
Lists all documents in your Onshape account, finds any with the same name,
keeps the newest copy of each, and deletes the older ones.

Requirements:
    pip install requests

Run via VS Code terminal:
    python delete_duplicates.py
"""

import sys
import time
import hmac
import hashlib
import base64
import random
import string
import requests
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent / '.env'
    keys = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                keys[k.strip()] = v.strip()
    return keys

_env = _load_env()
ACCESS_KEY = _env.get('ONSHAPE_ACCESS_KEY', '')
SECRET_KEY = _env.get('ONSHAPE_SECRET_KEY', '')

if not ACCESS_KEY or not SECRET_KEY:
    print("❌ Missing ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY in .env")
    sys.exit(1)

BASE_URL = "https://cad.onshape.com"
DELAY    = 1.0  # seconds between delete calls

# ── HMAC Auth ─────────────────────────────────────────────────────────────────
def _nonce():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=25))

def _headers(method, path, query='', ctype=''):
    n = _nonce()
    d = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    msg = f"{method}\n{n}\n{d}\n{ctype}\n{path}\n{query}\n".lower()
    sig = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    h = {
        'Authorization': f'On {ACCESS_KEY}:HmacSHA256:{sig}',
        'Date':     d,
        'On-Nonce': n,
        'Accept':   'application/json',
    }
    if ctype:
        h['Content-Type'] = ctype
    return h

def _get(path, query=''):
    h = _headers('get', path, query, '')
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else '')
    return requests.get(url, headers=h, timeout=30)

def _delete(path):
    h = _headers('delete', path, '', '')
    return requests.delete(f"{BASE_URL}{path}", headers=h, timeout=30)

def _call(fn, *args, retries=4):
    for _ in range(retries):
        r = fn(*args)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 60))
            print(f"\n  ⏳ Rate limited — waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue
        return r
    return r

# ── List all documents (paginated) ────────────────────────────────────────────
def list_all_documents():
    docs = []
    offset = 0
    while True:
        r = _call(_get, '/api/v6/documents', f'limit=20&offset={offset}')
        if r.status_code != 200:
            raise Exception(f"List failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        docs.extend(data.get('items', []))
        if not data.get('next'):
            break
        offset += 20
        time.sleep(0.4)
    return docs

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Onshape Duplicate Cleaner")
    print("=" * 60)

    # Auth check
    print("\nTesting authentication...", flush=True)
    r = _get('/api/v6/documents', 'limit=1')
    if r.status_code != 200:
        print(f"❌ Auth failed: {r.status_code}\n{r.text[:400]}")
        sys.exit(1)
    print("✓ Authenticated\n")

    # Fetch all documents
    print("Fetching all documents...", flush=True)
    docs = list_all_documents()
    print(f"Found {len(docs)} documents total.\n")

    # Group by name, sort each group newest → oldest
    by_name = defaultdict(list)
    for doc in docs:
        by_name[doc['name']].append(doc)

    # Sort each group: newest createdAt first
    for name in by_name:
        by_name[name].sort(
            key=lambda d: d.get('createdAt', ''),
            reverse=True
        )

    # Find duplicates
    duplicates = {name: copies for name, copies in by_name.items() if len(copies) > 1}

    if not duplicates:
        print("✅ No duplicates found — account is clean.")
        return

    # Summary
    to_delete = sum(len(v) - 1 for v in duplicates.values())
    print(f"Found {len(duplicates)} document names with duplicates ({to_delete} to delete):\n")
    for name, copies in sorted(duplicates.items()):
        print(f"  '{name}'  →  {len(copies)} copies, keeping newest, deleting {len(copies)-1}")

    print()
    confirm = input(f"Delete {to_delete} duplicate documents? Type YES to continue: ").strip()
    if confirm != "YES":
        print("Aborted.")
        return

    # Delete all but the newest of each group
    print()
    deleted = 0
    failed  = 0
    for name, copies in sorted(duplicates.items()):
        keep = copies[0]  # newest
        to_del = copies[1:]  # older ones
        print(f"  '{name}'  keeping id={keep['id'][:8]}...", flush=True)
        for doc in to_del:
            did = doc['id']
            print(f"    Deleting id={did[:8]}...", end='', flush=True)
            r = _call(_delete, f'/api/v6/documents/{did}')
            if r.status_code in (200, 204):
                print(" ✓")
                deleted += 1
            else:
                print(f" ✗ {r.status_code}: {r.text[:80]}")
                failed += 1
            time.sleep(DELAY)

    print(f"\n{'=' * 60}")
    print(f"  ✅ Deleted {deleted} duplicates")
    if failed:
        print(f"  ❌ {failed} deletions failed")
    print("=" * 60)

if __name__ == '__main__':
    main()
