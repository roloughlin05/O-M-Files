#!/usr/bin/env python3
"""
Onshape CAD Uploader
--------------------
Upload any CAD file(s) into your Onshape account.
Supports: STEP, IGES, STL, Parasolid, ACIS, DXF, DWG, and more.

Authenticates via your existing browser session — no API key required.

Run:
    python onshape_uploader.py
"""

import sys
import subprocess
import traceback
import tkinter as tk
from tkinter import filedialog

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

try:
    import browser_cookie3
except ImportError:
    install("browser-cookie3")
    import browser_cookie3

import time
import uuid
from pathlib import Path

BASE_URL = "https://cad.onshape.com"

SUPPORTED_EXTENSIONS = (
    ".stp", ".step", ".igs", ".iges", ".stl", ".sat", ".x_t", ".x_b",
    ".xmt_txt", ".xmt_bin", ".prt", ".asm", ".sldprt", ".sldasm",
    ".ipt", ".iam", ".dxf", ".dwg", ".obj", ".3dxml",
)

# ── Session setup ──────────────────────────────────────────────────────────────
def get_session():
    print("Reading Onshape session from browser cookies...", flush=True)

    browsers = [
        ("Brave",  browser_cookie3.brave),
        ("Chrome", browser_cookie3.chrome),
        ("Edge",   browser_cookie3.edge),
    ]

    cookiejar = None
    for name, loader in browsers:
        try:
            jar = loader(domain_name='.onshape.com')
            if any(c.name == 'XSRF-TOKEN' for c in jar):
                print(f"  ✓ Found session in {name}", flush=True)
                cookiejar = jar
                break
            else:
                print(f"  · {name}: no Onshape session found", flush=True)
        except Exception as e:
            print(f"  · {name}: {e}", flush=True)

    if cookiejar is None:
        print()
        print("  Auto-read failed. Try running as administrator, or use manual mode below.")
        print()
        print("  ── Manual cookie input ─────────────────────────────────────────")
        print("  1. Open Onshape in your browser and make sure you are logged in")
        print("  2. Press F12 to open DevTools")
        print("  3. Go to the Network tab and reload the page (Ctrl+R)")
        print("  4. Click any request to cad.onshape.com")
        print("  5. Under Request Headers, find the 'cookie:' line")

        print("  6. Right-click → Copy Value, then paste it below")
        print()
        cookie_str = input("  Paste cookies here: ").strip()
        if not cookie_str:
            raise RuntimeError("No cookies provided.")

        session = requests.Session()
        for part in cookie_str.split(';'):
            part = part.strip()
            if '=' in part:
                name, _, value = part.partition('=')
                session.cookies.set(name.strip(), value.strip(), domain='cad.onshape.com')

        xsrf = session.cookies.get('XSRF-TOKEN')
        if not xsrf:
            raise RuntimeError(
                "XSRF-TOKEN not found in pasted cookies.\n"
                "Make sure you copied the full 'cookie:' header value."
            )
        session.headers.update({'X-XSRF-TOKEN': xsrf, 'Accept': 'application/json'})
        return session

    session = requests.Session()
    session.cookies = cookiejar
    xsrf = next((c.value for c in cookiejar if c.name == 'XSRF-TOKEN'), None)
    session.headers.update({'X-XSRF-TOKEN': xsrf, 'Accept': 'application/json'})
    return session


# ── Folder browser ─────────────────────────────────────────────────────────────
def list_folders(session):
    """Return a flat list of the user's top-level folders."""
    r = session.get(f"{BASE_URL}/api/v14/globaltreenodes/magic/2")
    if r.status_code != 200:
        return []
    items = r.json().get('items', [])
    return [i for i in items if i.get('jsonType') == 'folder-info']


def pick_folder(session):
    """
    Interactively let the user choose a destination folder.
    Returns folder_id or None (meaning root / My Onshape).
    """
    print()
    print("  ── Choose destination folder ───────────────────────────────────")
    folders = list_folders(session)

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
            if fid:
                return fid
            print("  No ID entered — defaulting to root.")
            return None

        if choice.isdigit() and 1 <= int(choice) <= len(folders):
            selected = folders[int(choice) - 1]
            print(f"  ✓ Destination: {selected['name']}")
            return selected['id']

        print("  Invalid choice — try again.")


# ── File helpers ───────────────────────────────────────────────────────────────
def pick_files():
    """Open a file picker dialog and return a list of selected Paths."""
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


def find_doc_by_name(session, name):
    """Return (doc_id, workspace_id) for the first document matching name."""
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


def create_document(session, name, folder_id=None):
    """Create a new Onshape document, optionally in a folder."""
    payload = {"name": name, "ownerType": 0}
    if folder_id:
        payload["parentId"] = folder_id
    r = session.post(f"{BASE_URL}/api/v6/documents", json=payload)
    r.raise_for_status()
    data = r.json()
    time.sleep(1.0)
    return data['id'], data['defaultWorkspace']['id']


def upload_blob(session, doc_id, workspace_id, filepath: Path):
    """Upload a CAD file as a blob element to an Onshape document."""
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

    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    path    = f"/api/v6/blobelements/d/{doc_id}/w/{workspace_id}"

    print(f"   Uploading to Onshape (this may take a minute)...", flush=True)
    r = session.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=300)
    return r


def wait_for_translation(session, doc_id, workspace_id, timeout=300):
    """
    Poll the document's element list until a translated (non-blob) element
    appears, indicating Onshape has finished processing the uploaded file.
    Returns True on success, False on timeout or error.
    """
    print(f"   Waiting for Onshape to translate file", end='', flush=True)
    path  = f"{BASE_URL}/api/v6/documents/{doc_id}/workspaces/{workspace_id}/elements"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = session.get(path, timeout=15)
            if r.status_code == 200:
                elements = r.json()
                # Translation is done when at least one non-BLOB element exists
                if any(e.get('type', '').upper() != 'BLOB' for e in elements):
                    print(" ✓", flush=True)
                    return True
        except Exception:
            pass
        print('.', end='', flush=True)
        time.sleep(10)
    print(" ⏱ timed out — proceeding anyway", flush=True)
    return False


def create_version(session, doc_id, workspace_id, version_name, description=""):
    """
    Create a named, immutable version from the current workspace state.
    This is Onshape's equivalent of tagging a release.
    """
    path = f"{BASE_URL}/api/v6/documents/{doc_id}/workspaces/{workspace_id}/versions"
    r = session.post(path, json={"name": version_name, "description": description})
    if r.status_code in (200, 201):
        vid = r.json().get('id', '')[:8]
        print(f"   ✓ Version '{version_name}' created  id={vid}...")
    else:
        print(f"   ⚠ Version creation failed: {r.status_code} {r.text[:120]}")
    return r


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Onshape CAD Uploader")
    print("=" * 60)
    print()

    # Authenticate
    session = get_session()
    r = session.get(f"{BASE_URL}/api/v6/documents?limit=1")
    if r.status_code != 200:
        raise RuntimeError(
            f"Session auth failed (HTTP {r.status_code}).\n"
            "Are you logged into Onshape in your browser?"
        )
    print("  ✓ Authenticated\n")

    # Pick files
    print("  Opening file picker...")
    files = pick_files()
    if not files:
        print("  No files selected — exiting.")
        return

    print(f"\n  {len(files)} file(s) selected:")
    for f in files:
        print(f"    • {f.name}")

    # Pick destination folder (shared for all files in this batch)
    folder_id = pick_folder(session)

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

    # Confirm document names and upload mode for each file
    print()
    print("  ── Upload settings ─────────────────────────────────────────────")
    tasks = []
    for filepath in files:
        default_name = filepath.stem  # filename without extension
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
            doc_id, ws_id = find_doc_by_name(session, task['doc_name'])
            if not doc_id:
                print(f"  ⚠️  Document not found — creating new one")
                doc_id, ws_id = create_document(session, task['doc_name'], task['folder_id'])
                print(f"  ✓ Created  id={doc_id[:8]}...")
            else:
                print(f"  ✓ Found    id={doc_id[:8]}...")
        else:
            print(f"  Action   : create new document", flush=True)
            doc_id, ws_id = create_document(session, task['doc_name'], task['folder_id'])
            print(f"  ✓ Created  id={doc_id[:8]}...")

        r = upload_blob(session, doc_id, ws_id, task['file_path'])
        if r.status_code in (200, 201):
            print(f"  ✅ Upload accepted — waiting for translation...")
            translated = wait_for_translation(session, doc_id, ws_id)
            if translated:
                create_version(session, doc_id, ws_id, version_name, version_desc)
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
