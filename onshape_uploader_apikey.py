#!/usr/bin/env python3
"""
Onshape CAD Uploader — API Key Version
---------------------------------------
Upload any CAD file(s) into your Onshape account using an API key.
Supports: STEP, IGES, STL, Parasolid, ACIS, DXF, DWG, and more.

Requires a .env file in the same folder as this script containing:
    ONSHAPE_ACCESS_KEY=your_access_key
    ONSHAPE_SECRET_KEY=your_secret_key

Get your API keys at: https://dev-portal.onshape.com/keys

Run:
    python onshape_uploader_apikey.py

Note: Onshape API keys have a quota of 2,500 requests/year on free plans.
For unlimited requests, use onshape_uploader.py (browser session version).
"""

import sys
import subprocess
import traceback
import hmac
import hashlib
import base64
import random
import string
import uuid
import tkinter as tk
from tkinter import filedialog
from datetime import datetime, timezone
from pathlib import Path

# ── Auto-install dependencies ──────────────────────────────────────────────────
def install(pkg):
    print(f"  Installing {pkg}...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", pkg, "--break-system-packages", "-q"]
    )

try:
    import requests
except ImportError:
    install("requests")
    import requests

import time

BASE_URL = "https://cad.onshape.com"

SUPPORTED_EXTENSIONS = (
    ".stp", ".step", ".igs", ".iges", ".stl", ".sat", ".x_t", ".x_b",
    ".xmt_txt", ".xmt_bin", ".prt", ".asm", ".sldprt", ".sldasm",
    ".ipt", ".iam", ".dxf", ".dwg", ".obj", ".3dxml",
)

# ── API key setup ──────────────────────────────────────────────────────────────
def load_api_keys():
    """Read ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY from .env."""
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        raise RuntimeError(
            ".env file not found.\n"
            f"Expected: {env_path}\n\n"
            "Create a .env file with:\n"
            "    ONSHAPE_ACCESS_KEY=your_access_key\n"
            "    ONSHAPE_SECRET_KEY=your_secret_key\n\n"
            "Get API keys at: https://dev-portal.onshape.com/keys"
        )

    keys = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            keys[k.strip()] = v.strip()

    access = keys.get('ONSHAPE_ACCESS_KEY', '')
    secret = keys.get('ONSHAPE_SECRET_KEY', '')

    if not access or not secret:
        raise RuntimeError(
            "ONSHAPE_ACCESS_KEY or ONSHAPE_SECRET_KEY missing from .env.\n"
            "Make sure both keys are present and have no extra spaces."
        )

    return access, secret


# ── HMAC auth ──────────────────────────────────────────────────────────────────
def _nonce():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=25))


def _make_headers(access_key, secret_key, method, path, query='', content_type=''):
    n = _nonce()
    d = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')
    msg = f"{method}\n{n}\n{d}\n{content_type}\n{path}\n{query}\n".lower()
    sig = base64.b64encode(
        hmac.new(secret_key.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        'Authorization': f'On {access_key}:HmacSHA256:{sig}',
        'Date':     d,
        'On-Nonce': n,
        'Accept':   'application/json',
    }
    if content_type:
        headers['Content-Type'] = content_type
    return headers


# ── Request helpers ────────────────────────────────────────────────────────────
def api_get(access_key, secret_key, path, query=''):
    h = _make_headers(access_key, secret_key, 'get', path, query)
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else '')
    return requests.get(url, headers=h, timeout=30)


def api_post_json(access_key, secret_key, path, body):
    ctype = 'application/json'
    h = _make_headers(access_key, secret_key, 'post', path, '', ctype)
    return requests.post(f"{BASE_URL}{path}", headers=h, json=body, timeout=30)


def wait_for_translation(access_key, secret_key, doc_id, workspace_id, timeout=300):
    """
    Poll the document's element list until a translated (non-blob) element
    appears, indicating Onshape has finished processing the uploaded file.
    Returns True on success, False on timeout or error.
    """
    print(f"   Waiting for Onshape to translate file", end='', flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = api_get(access_key, secret_key,
                        f'/api/v6/documents/{doc_id}/workspaces/{workspace_id}/elements')
            if r.status_code == 200:
                elements = r.json()
                if any(e.get('type', '').upper() != 'BLOB' for e in elements):
                    print(" ✓", flush=True)
                    return True
        except Exception:
            pass
        print('.', end='', flush=True)
        time.sleep(10)
    print(" ⏱ timed out — proceeding anyway", flush=True)
    return False


def create_version(access_key, secret_key, doc_id, workspace_id, version_name, description=""):
    """
    Create a named, immutable version from the current workspace state.
    This is Onshape's equivalent of tagging a release.
    """
    r = api_post_json(access_key, secret_key,
                      f'/api/v6/documents/{doc_id}/workspaces/{workspace_id}/versions',
                      {"name": version_name, "description": description})
    if r.status_code in (200, 201):
        vid = r.json().get('id', '')[:8]
        print(f"   ✓ Version '{version_name}' created  id={vid}...")
    else:
        print(f"   ⚠ Version creation failed: {r.status_code} {r.text[:120]}")
    return r


def api_post_file(access_key, secret_key, path, filepath: Path):
    """Upload a file using multipart form-data with a pre-signed boundary."""
    boundary = uuid.uuid4().hex
    size_mb   = filepath.stat().st_size / 1024 / 1024

    print(f"   Reading {filepath.name} ({size_mb:.1f} MB)...", flush=True)
    file_data = filepath.read_bytes()

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filepath.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n'
        f'\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()

    ctype = f'multipart/form-data; boundary={boundary}'
    h = _make_headers(access_key, secret_key, 'post', path, '', ctype)

    print(f"   Uploading to Onshape (this may take a minute)...", flush=True)
    return requests.post(f"{BASE_URL}{path}", headers=h, data=body, timeout=300)


# ── Folder browser ─────────────────────────────────────────────────────────────
def list_folders(access_key, secret_key):
    r = api_get(access_key, secret_key, '/api/v14/globaltreenodes/magic/2')
    if r.status_code != 200:
        return []
    return [i for i in r.json().get('items', []) if i.get('jsonType') == 'folder-info']


def pick_folder(access_key, secret_key):
    print()
    print("  ── Choose destination folder ───────────────────────────────────")
    folders = list_folders(access_key, secret_key)

    if folders:
        print("  Your top-level Onshape folders:")
        for i, f in enumerate(folders, 1):
            print(f"    [{i}] {f['name']}")
    print(f"    [0] My Onshape (root — no folder)")
    print(f"    [M] Enter a folder ID manually")
    print()

    while True:
        choice = input("  Select destination [0]: ").strip() or "0"

        if choice == "0":
            return None
        if choice.upper() == "M":
            fid = input("  Paste folder ID: ").strip()
            return fid if fid else None
        if choice.isdigit() and 1 <= int(choice) <= len(folders):
            selected = folders[int(choice) - 1]
            print(f"  ✓ Destination: {selected['name']}")
            return selected['id']

        print("  Invalid choice — try again.")


# ── Document helpers ───────────────────────────────────────────────────────────
def find_doc_by_name(access_key, secret_key, name):
    offset = 0
    while True:
        r = api_get(access_key, secret_key, '/api/v6/documents', f'limit=20&offset={offset}')
        r.raise_for_status()
        data = r.json()
        for doc in data.get('items', []):
            if doc['name'] == name:
                return doc['id'], doc['defaultWorkspace']['id']
        if not data.get('next'):
            return None, None
        offset += 20


def create_document(access_key, secret_key, name, folder_id=None):
    payload = {"name": name, "ownerType": 0}
    if folder_id:
        payload["parentId"] = folder_id
    r = api_post_json(access_key, secret_key, '/api/v6/documents', payload)
    r.raise_for_status()
    data = r.json()
    time.sleep(1.0)
    return data['id'], data['defaultWorkspace']['id']


# ── File picker ────────────────────────────────────────────────────────────────
def pick_files():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    ext_list = " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS)
    files = filedialog.askopenfilenames(
        title="Select CAD files to upload to Onshape",
        filetypes=[
            ("CAD files", ext_list),
            ("STEP files", "*.stp *.step"),
            ("IGES files", "*.igs *.iges"),
            ("STL files", "*.stl"),
            ("All files", "*.*"),
        ]
    )
    root.destroy()
    return [Path(f) for f in files]


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Onshape CAD Uploader — API Key Version")
    print("=" * 60)
    print()

    # Load credentials
    access_key, secret_key = load_api_keys()

    # Auth check
    r = api_get(access_key, secret_key, '/api/v6/documents', 'limit=1')
    if r.status_code != 200:
        raise RuntimeError(
            f"API auth failed (HTTP {r.status_code}).\n"
            "Check that your ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY are correct."
        )
    print("  ✓ Authenticated with API key\n")

    # Pick files
    print("  Opening file picker...")
    files = pick_files()
    if not files:
        print("  No files selected — exiting.")
        return

    print(f"\n  {len(files)} file(s) selected:")
    for f in files:
        print(f"    • {f.name}")

    # Pick destination folder
    folder_id = pick_folder(access_key, secret_key)

    # Version name
    print()
    print("  ── Version settings ────────────────────────────────────────────")
    print("  After each upload Onshape will create a named version (snapshot).")
    print("  This marks the imported file as a stable release in Onshape's")
    print("  version history, making it easy to branch or roll back later.")
    print()
    default_version = "v1.0 - Initial Import"
    version_name = input(f"  Version name [{default_version}]: ").strip() or default_version
    version_desc = input(f"  Version description (optional): ").strip()

    # Confirm document names and upload mode per file
    print()
    print("  ── Upload settings ─────────────────────────────────────────────")
    tasks = []
    for filepath in files:
        default_name = filepath.stem
        print(f"\n  File: {filepath.name}")
        doc_name = input(f"  Document name [{default_name}]: ").strip() or default_name

        print(f"  Upload mode:")
        print(f"    [1] Create a new document (default)")
        print(f"    [2] Add to an existing document")
        mode = input("  Choice [1]: ").strip() or "1"

        tasks.append({
            "file_path": filepath,
            "doc_name":  doc_name,
            "action":    "upload_to_existing" if mode == "2" else "create_and_upload",
            "folder_id": folder_id,
        })

    # Upload
    print()
    print("=" * 60)
    print("  Starting uploads...")
    print("=" * 60)

    for task in tasks:
        print(f"\n{'─' * 60}")
        print(f"  Document : {task['doc_name']}")
        print(f"  File     : {task['file_path'].name}")

        if task['action'] == 'upload_to_existing':
            print(f"  Action   : add to existing document", flush=True)
            doc_id, ws_id = find_doc_by_name(access_key, secret_key, task['doc_name'])
            if not doc_id:
                print(f"  ⚠️  Document not found — creating new one")
                doc_id, ws_id = create_document(access_key, secret_key, task['doc_name'], task['folder_id'])
                print(f"  ✓ Created  id={doc_id[:8]}...")
            else:
                print(f"  ✓ Found    id={doc_id[:8]}...")
        else:
            print(f"  Action   : create new document", flush=True)
            doc_id, ws_id = create_document(access_key, secret_key, task['doc_name'], task['folder_id'])
            print(f"  ✓ Created  id={doc_id[:8]}...")

        blob_path = f'/api/v6/blobelements/d/{doc_id}/w/{ws_id}'
        r = api_post_file(access_key, secret_key, blob_path, task['file_path'])

        if r.status_code in (200, 201):
            print(f"  ✅ Upload accepted — waiting for translation...")
            translated = wait_for_translation(access_key, secret_key, doc_id, ws_id)
            if translated:
                create_version(access_key, secret_key, doc_id, ws_id, version_name, version_desc)
            else:
                print(f"  ⚠ Translation may still be in progress.")
                print(f"    You can create the version manually in Onshape once it finishes.")
        else:
            print(f"  ❌ Upload failed: HTTP {r.status_code}")
            print(f"     {r.text[:400]}")

        time.sleep(1.0)

    print()
    print("=" * 60)
    print("  All done! Open Onshape to see your models.")
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
