#!/usr/bin/env python3
"""
Onshape Bulk Import Script
---------------------------
1. Snapshots existing account contents
2. Imports .ipt, .iam, .stp, .STEP files organized by subfolder
3. Optionally deletes old documents/folders after upload

Requirements:
    pip install requests

Run via VS Code terminal:
    python onshape_import.py
"""

import sys
import time
import hmac
import hashlib
import base64
import random
import string
import json
import uuid
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
def _load_env():
    """Read ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY from .env in the script folder."""
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
    print("❌ Could not find ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY in .env")
    print(f"   Expected a .env file at: {Path(__file__).parent / '.env'}")
    input("\nPress Enter to exit...")
    sys.exit(1)

BASE_URL   = "https://cad.onshape.com"

FILES_ROOT = Path(__file__).parent
EXTS       = {'.ipt', '.iam', '.stp', '.step'}
DELAY      = 1.2   # seconds between API calls
LOG_FILE   = FILES_ROOT / "import_log.json"

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

# ── Request helpers ───────────────────────────────────────────────────────────
def _get(path, query=''):
    h = _headers('get', path, query, '')
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else '')
    return requests.get(url, headers=h, timeout=30)

def _post_json(path, body):
    ctype = 'application/json'
    h = _headers('post', path, '', ctype)
    return requests.post(f"{BASE_URL}{path}", headers=h, json=body, timeout=30)

def _delete(path):
    h = _headers('delete', path, '', '')
    return requests.delete(f"{BASE_URL}{path}", headers=h, timeout=30)

def _post_file(path, filepath: Path):
    # Pre-generate the boundary (lowercase hex) so we can include the FULL
    # Content-Type (with boundary) in the HMAC signature before sending.
    # This avoids the mismatch caused by requests generating the boundary
    # after the signature is already computed.
    boundary = uuid.uuid4().hex  # e.g. 'a3f1c2d4...' — already lowercase

    with open(filepath, 'rb') as f:
        file_data = f.read()

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filepath.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n'
        f'\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

    ctype = f'multipart/form-data; boundary={boundary}'
    h = _headers('post', path, '', ctype)   # signs with exact ctype incl. boundary

    return requests.post(
        f"{BASE_URL}{path}",
        headers=h,
        data=body,
        timeout=180,
    )

def _call(fn, *args, retries=4, **kwargs):
    """Retry on 429 rate-limit responses."""
    for attempt in range(retries):
        r = fn(*args, **kwargs)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 60))
            print(f"\n    ⏳ Rate limited — waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue
        return r
    return r

# ── Onshape operations ────────────────────────────────────────────────────────
def list_all_documents():
    """Return list of all {id, name} dicts across all pages."""
    docs = []
    offset = 0
    while True:
        r = _call(_get, '/api/v6/documents', f'limit=20&offset={offset}')
        if r.status_code != 200:
            raise Exception(f"List docs failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        items = data.get('items', [])
        docs.extend(items)
        if not data.get('next'):
            break
        offset += 20
        time.sleep(0.5)
    return docs

def list_all_folders():
    """Return list of all {id, name} folder dicts across all pages."""
    folders = []
    offset = 0
    while True:
        r = _call(_get, '/api/v6/folders', f'limit=20&offset={offset}')
        if r.status_code != 200:
            break  # endpoint may not exist on all plans; skip silently
        data = r.json()
        items = data.get('items', [])
        folders.extend(items)
        if not data.get('next'):
            break
        offset += 20
        time.sleep(0.5)
    return folders

def wipe_account():
    """Delete every document and folder in the account."""
    print("  Fetching document list...", flush=True)
    docs = list_all_documents()
    print(f"  Found {len(docs)} documents to delete.")

    for i, doc in enumerate(docs, 1):
        did  = doc['id']
        name = doc.get('name', did)
        print(f"  [{i:>4}/{len(docs)}] Deleting '{name}'...", end='', flush=True)
        r = _call(_delete, f'/api/v6/documents/{did}')
        if r.status_code in (200, 204):
            print(" ✓")
        else:
            print(f" ✗ {r.status_code}: {r.text[:100]}")
        time.sleep(DELAY)

    print("\n  Fetching folder list...", flush=True)
    folders = list_all_folders()
    print(f"  Found {len(folders)} folders to delete.")

    for i, folder in enumerate(folders, 1):
        fid  = folder['id']
        name = folder.get('name', fid)
        print(f"  [{i:>4}/{len(folders)}] Deleting folder '{name}'...", end='', flush=True)
        r = _call(_delete, f'/api/v6/folders/{fid}')
        if r.status_code in (200, 204):
            print(" ✓")
        else:
            print(f" ✗ {r.status_code}: {r.text[:100]}")
        time.sleep(DELAY)

def create_folder(name):
    body = {"name": name, "ownerType": 0}
    r = _call(_post_json, '/api/v6/folders', body)
    if r.status_code not in (200, 201):
        raise Exception(f"{r.status_code} {r.text[:300]}")
    time.sleep(DELAY)
    return r.json()['id']

def create_document(name, folder_id):
    body = {"name": name, "ownerType": 0, "parentId": folder_id}
    r = _call(_post_json, '/api/v6/documents', body)
    if r.status_code not in (200, 201):
        raise Exception(f"{r.status_code} {r.text[:300]}")
    data = r.json()
    time.sleep(DELAY)
    return data['id'], data['defaultWorkspace']['id']

def upload_blob(did, wid, filepath: Path):
    path = f'/api/v6/blobelements/d/{did}/w/{wid}'
    r = _call(_post_file, path, filepath)
    time.sleep(DELAY)
    return r

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log = {"folders": {}, "errors": [], "summary": {}}

    # 1. Auth check
    print("=" * 60)
    print("  Onshape Bulk Import")
    print("=" * 60)
    print("\nTesting Onshape authentication...", flush=True)
    r = _get('/api/v6/documents', 'limit=1')
    if r.status_code != 200:
        print(f"\n❌ Auth failed: {r.status_code}")
        print(r.text[:600])
        sys.exit(1)
    print("✓ Authenticated successfully\n")

    # 2. Snapshot existing documents & folders BEFORE importing
    print("─" * 60)
    print("PHASE 1 — Snapshotting existing account contents")
    print("─" * 60)
    print("  Fetching existing documents...", flush=True)
    existing_docs    = list_all_documents()
    existing_folders = list_all_folders()
    existing_doc_ids    = {d['id'] for d in existing_docs}
    existing_folder_ids = {f['id'] for f in existing_folders}
    print(f"  Found {len(existing_docs)} existing documents and {len(existing_folders)} existing folders.\n")

    # 3. Import
    print("─" * 60)
    print("PHASE 2 — Importing files")
    print("─" * 60)
    subfolders = sorted([d for d in FILES_ROOT.iterdir() if d.is_dir()])
    plan = {}
    total = 0
    print("Files found:")
    for sf in subfolders:
        files = sorted([f for f in sf.rglob('*') if f.suffix.lower() in EXTS])
        if files:
            plan[sf] = files
            total += len(files)
            print(f"  {sf.name}: {len(files)} files")
    print(f"\nTotal to import: {total} files")
    print(f"Estimated time:  ~{int(total * DELAY * 2 / 60)} minutes\n")

    done = 0
    errors = []

    for sf, files in plan.items():
        print(f"{'─' * 60}")
        print(f"📁 {sf.name}  ({len(files)} files)")

        try:
            folder_id = create_folder(sf.name)
            print(f"   Onshape folder created  id={folder_id[:8]}...")
            log["folders"][sf.name] = {"id": folder_id, "files": []}
        except Exception as e:
            msg = str(e)
            print(f"   ❌ Could not create folder: {msg}")
            errors.append({"folder": sf.name, "error": msg})
            log["errors"].append({"folder": sf.name, "error": msg})
            continue

        for i, fp in enumerate(files, 1):
            tag = f"  [{i:>3}/{len(files)}] {fp.name}"
            print(f"{tag}...", end='', flush=True)
            entry = {"file": fp.name, "status": "error", "doc_id": None}
            try:
                did, wid = create_document(fp.stem, folder_id)
                r = upload_blob(did, wid, fp)
                if r.status_code in (200, 201):
                    print(" ✓")
                    done += 1
                    entry["status"] = "ok"
                    entry["doc_id"] = did
                else:
                    msg = f"upload {r.status_code}: {r.text[:150]}"
                    print(f"\n     ✗ {msg}")
                    errors.append({"file": fp.name, "error": msg})
                    entry["error"] = msg
            except Exception as e:
                print(f"\n     ✗ {e}")
                errors.append({"file": fp.name, "error": str(e)})
                entry["error"] = str(e)

            log["folders"][sf.name]["files"].append(entry)

    # 4. Delete old duplicates now that upload is complete
    print(f"\n{'─' * 60}")
    print("PHASE 3 — Deleting old documents and folders")
    print("─" * 60)

    if not existing_doc_ids and not existing_folder_ids:
        print("  Nothing to delete — account was already empty before import.")
    else:
        confirm = input(
            f"  ⚠️  Delete {len(existing_doc_ids)} old documents and "
            f"{len(existing_folder_ids)} old folders?\n  Type YES to continue: "
        ).strip()

        if confirm != "YES":
            print("  Skipped — old files left in place.")
        else:
            print()
            del_doc_ok = del_doc_fail = 0
            for i, did in enumerate(existing_doc_ids, 1):
                print(f"  [{i:>4}/{len(existing_doc_ids)}] Deleting old document...", end='', flush=True)
                r = _call(_delete, f'/api/v6/documents/{did}')
                if r.status_code in (200, 204):
                    print(" ✓")
                    del_doc_ok += 1
                else:
                    print(f" ✗ {r.status_code}: {r.text[:80]}")
                    del_doc_fail += 1
                time.sleep(DELAY)

            del_fol_ok = del_fol_fail = 0
            for i, fid in enumerate(existing_folder_ids, 1):
                print(f"  [{i:>4}/{len(existing_folder_ids)}] Deleting old folder...", end='', flush=True)
                r = _call(_delete, f'/api/v6/folders/{fid}')
                if r.status_code in (200, 204):
                    print(" ✓")
                    del_fol_ok += 1
                else:
                    print(f" ✗ {r.status_code}: {r.text[:80]}")
                    del_fol_fail += 1
                time.sleep(DELAY)

            print(f"\n  Deleted {del_doc_ok} documents, {del_fol_ok} folders.")
            if del_doc_fail or del_fol_fail:
                print(f"  ⚠️  {del_doc_fail} doc deletions and {del_fol_fail} folder deletions failed.")

    # 5. Save log & summary
    log["summary"] = {"total": total, "succeeded": done, "failed": len(errors)}
    LOG_FILE.write_text(json.dumps(log, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  ✅ {done}/{total} files imported successfully")
    if errors:
        print(f"  ❌ {len(errors)} import errors — see import_log.json")
    print(f"  📄 Log: {LOG_FILE}")
    print("=" * 60)

if __name__ == '__main__':
    main()
