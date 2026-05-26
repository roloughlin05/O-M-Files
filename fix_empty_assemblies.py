#!/usr/bin/env python3
"""
Fix Empty Assembly Documents
-----------------------------
Uploads BV-ASM-222-100.stp and Tower Assm.stp into Onshape using
your existing Chrome browser session (no API key quota used).

Run directly in VS Code terminal:
    python fix_empty_assemblies.py
"""

import sys
import subprocess
import traceback

# ── Auto-install dependencies before importing them ────────────────────────────
def install(pkg):
    print(f"Installing {pkg}...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"]
    )

try:
    import requests
except ImportError:
    install("requests")
    import requests

try:
    import browser_cookie3
except ImportError:
    install("browser-cookie3")
    import browser_cookie3

import time
import uuid
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL   = "https://cad.onshape.com"
FILES_ROOT = Path(__file__).parent

UPLOADS = [
    {
        "doc_name":  "BV-ASM-222-100",
        "file_path": FILES_ROOT / "BASE VEHICLE DESIGN PROJECT" / "BV-ASM-222-100 STEP Files" / "BV-ASM-222-100.stp",
        "folder_id": "7c6193d69bbdace5cab56bcd",   # Base Vehicle / Assemblies
        "action":    "upload_to_existing",           # doc already exists but is empty
    },
    {
        "doc_name":  "Tower Assm",
        "file_path": FILES_ROOT / "CLEANING ROBOT TOWER PROJECT" / "Tower Assm STEP Files" / "Tower Assm.stp",
        "folder_id": "075b46f49367baba8e0d47bb",   # Tower / Assemblies
        "action":    "create_and_upload",            # doc doesn't exist yet
    },
]

# ── Session setup ──────────────────────────────────────────────────────────────
def get_session():
    print("Reading Onshape session from browser cookies...", flush=True)

    # Try Brave, then Chrome, then Edge — whichever has Onshape cookies
    browsers = [
        ("Brave",  browser_cookie3.brave),
        ("Chrome", browser_cookie3.chrome),
        ("Edge",   browser_cookie3.edge),
    ]

    cookiejar = None
    for name, loader in browsers:
        try:
            jar = loader(domain_name='.onshape.com')
            # Check that it actually has an XSRF token (i.e. user is logged in)
            if any(c.name == 'XSRF-TOKEN' for c in jar):
                print(f"  ✓ Found session in {name}", flush=True)
                cookiejar = jar
                break
            else:
                print(f"  · {name}: no Onshape session found", flush=True)
        except Exception as e:
            print(f"  · {name}: {e}", flush=True)

    if cookiejar is None:
        # ── Manual fallback ────────────────────────────────────────────────────
        print()
        print("  Auto-read failed (try running VS Code as administrator to fix this).")
        print()
        print("  ── Manual cookie fallback ──────────────────────────────────────")
        print("  1. Open Onshape in Brave and make sure you're logged in")
        print("  2. Press F12 to open DevTools")
        print("  3. Go to the Network tab")
        print("  4. Reload the Onshape page (Ctrl+R)")
        print("  5. Click any request to cad.onshape.com in the list")
        print("  6. In the right panel, click 'Headers'")
        print("  7. Scroll to 'Request Headers' and find the 'cookie:' line")
        print("  8. Right-click that line → Copy Value")
        print()
        cookie_str = input("  Paste cookies here and press Enter: ").strip()
        if not cookie_str:
            raise RuntimeError("No cookies provided — exiting.")

        # Parse pasted cookie string into a session
        session = requests.Session()
        for part in cookie_str.split(';'):
            part = part.strip()
            if '=' in part:
                name, _, value = part.partition('=')
                session.cookies.set(name.strip(), value.strip(), domain='cad.onshape.com')

        xsrf = session.cookies.get('XSRF-TOKEN')
        if not xsrf:
            raise RuntimeError(
                "XSRF-TOKEN not found in the pasted cookies.\n"
                "Make sure you copied the full 'cookie:' header value."
            )
        session.headers.update({'X-XSRF-TOKEN': xsrf, 'Accept': 'application/json'})
        return session

    session = requests.Session()
    session.cookies = cookiejar

    xsrf = next((c.value for c in cookiejar if c.name == 'XSRF-TOKEN'), None)

    session.headers.update({
        'X-XSRF-TOKEN': xsrf,
        'Accept':        'application/json',
    })
    return session

# ── Helpers ────────────────────────────────────────────────────────────────────
def find_doc_by_name(session, name):
    """Return (doc_id, workspace_id) for the first document matching name, or (None, None)."""
    offset = 0
    while True:
        r = session.get(f"{BASE_URL}/api/v6/documents?limit=20&offset={offset}")
        r.raise_for_status()
        data = r.json()
        for doc in data.get('items', []):
            if doc['name'] == name:
                return doc['id'], doc['defaultWorkspace']['id']
        if not data.get('next'):
            return None, None
        offset += 20


def create_document(session, name, folder_id):
    """Create a new Onshape document in the given folder."""
    r = session.post(
        f"{BASE_URL}/api/v6/documents",
        json={"name": name, "ownerType": 0, "parentId": folder_id}
    )
    r.raise_for_status()
    data = r.json()
    time.sleep(1.0)
    return data['id'], data['defaultWorkspace']['id']


def upload_blob(session, doc_id, workspace_id, filepath: Path):
    """Upload a STEP file as a blob element to an Onshape document workspace."""
    boundary = uuid.uuid4().hex
    size_mb  = filepath.stat().st_size / 1024 / 1024

    print(f"   Reading {filepath.name} ({size_mb:.1f} MB)...", flush=True)
    file_data = filepath.read_bytes()

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filepath.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n'
        f'\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    path    = f"/api/v6/blobelements/d/{doc_id}/w/{workspace_id}"

    print(f"   Uploading to Onshape (this may take a minute)...", flush=True)
    r = session.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=300)
    return r

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Fix Empty Assembly Documents")
    print("=" * 60)
    print()

    session = get_session()

    # Quick auth check
    r = session.get(f"{BASE_URL}/api/v6/documents?limit=1")
    if r.status_code != 200:
        raise RuntimeError(
            f"Session auth failed (HTTP {r.status_code}).\n"
            "Are you logged into Onshape in Chrome?"
        )
    print("✓ Authenticated via browser session\n")

    for task in UPLOADS:
        print(f"{'─' * 60}")
        print(f"  Document : {task['doc_name']}")
        print(f"  File     : {task['file_path'].name}")

        if not task['file_path'].exists():
            print(f"  ❌ Source file not found:\n     {task['file_path']}")
            print(f"     Skipping this file.")
            continue

        if task['action'] == 'upload_to_existing':
            print(f"  Action   : upload into existing document", flush=True)
            doc_id, ws_id = find_doc_by_name(session, task['doc_name'])
            if not doc_id:
                print(f"  ⚠️  Document '{task['doc_name']}' not found — creating new one in target folder")
                doc_id, ws_id = create_document(session, task['doc_name'], task['folder_id'])
                print(f"  ✓ Created document  id={doc_id[:8]}...")
            else:
                print(f"  ✓ Found document    id={doc_id[:8]}...")
        else:
            print(f"  Action   : create new document + upload", flush=True)
            doc_id, ws_id = create_document(session, task['doc_name'], task['folder_id'])
            print(f"  ✓ Created document  id={doc_id[:8]}...")

        r = upload_blob(session, doc_id, ws_id, task['file_path'])
        if r.status_code in (200, 201):
            print(f"  ✅ Upload successful!")
        else:
            print(f"  ❌ Upload failed: HTTP {r.status_code}")
            print(f"     Response: {r.text[:400]}")

        time.sleep(1.0)

    print()
    print("=" * 60)
    print("  Done! Open Onshape to see the translated models.")
    print("  (Translation can take 1–2 minutes to complete.)")
    print("=" * 60)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        main()
    except Exception:
        print()
        print("=" * 60)
        print("  ERROR — full details below:")
        print("=" * 60)
        traceback.print_exc()
    finally:
        input("\nPress Enter to exit...")
