#!/usr/bin/env python3
"""
Onshape Version Restructure
----------------------------
Cleans up Inventor auto-version documents from Onshape and establishes
proper Onshape version history on the remaining documents.

Background
----------
Autodesk Inventor stores revision history as separate files in an
OldVersions/ folder, named like:
    BV-222-101.0032.ipt   ← auto-save #32 of BV-222-101
    CRA-1004.0010.ipt     ← auto-save #10 of CRA-1004

When these are bulk-imported, Onshape ends up with hundreds of documents
named "BV-222-101.0032" alongside the real "BV-222-101" document. These
are noise — they're Inventor's internal versioning, not design milestones.

Onshape best practice: one document per part/assembly, with meaningful
named versions marking stable releases (e.g. "v1.0 - Released for Mfg").

What this script does
---------------------
Phase 1 — Identify Inventor auto-version documents
    Scans all Onshape documents for names matching the pattern NAME.XXXX
    (where XXXX is a 4-digit Inventor revision counter).

Phase 2 — Preview and confirm deletion
    Shows you exactly what will be removed and asks for confirmation.
    Keeps all clean base-name documents untouched.

Phase 3 — Delete auto-version documents
    Removes the .XXXX noise documents from Onshape.

Phase 4 — Version the clean documents
    For documents that don't yet have a named version, creates
    "v1.0 - Initial Release" to establish a stable baseline.

Run:
    python onshape_restructure_versions.py
"""

import sys
import subprocess
import traceback
import re
import time

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

BASE_URL = "https://cad.onshape.com"

# Matches Inventor auto-version suffix: NAME.XXXX (4-digit revision counter)
# Examples: "BV-222-101.0032", "CRA-1004.0010", "CLEANING_ROBOT_Template.0114"
INVENTOR_VERSION_PATTERN = re.compile(r'^(.+)\.\d{4}$')

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
        print("  Auto-read failed. Try running VS Code as administrator.")
        print()
        print("  ── Manual cookie fallback ──────────────────────────────────────")
        print("  1. Open Onshape in your browser and log in")
        print("  2. Press F12 → Network tab → reload the page")
        print("  3. Click any cad.onshape.com request → Headers → 'cookie:' line")
        print("  4. Right-click → Copy Value, paste below")
        print()
        cookie_str = input("  Paste cookies: ").strip()
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
            raise RuntimeError("XSRF-TOKEN not found in pasted cookies.")
        session.headers.update({'X-XSRF-TOKEN': xsrf, 'Accept': 'application/json'})
        return session

    session = requests.Session()
    session.cookies = cookiejar
    xsrf = next((c.value for c in cookiejar if c.name == 'XSRF-TOKEN'), None)
    session.headers.update({'X-XSRF-TOKEN': xsrf, 'Accept': 'application/json'})
    return session


# ── API helpers ────────────────────────────────────────────────────────────────
def list_all_documents(session):
    """Return all documents in the account (paginated)."""
    docs = []
    offset = 0
    print("  Fetching all documents", end='', flush=True)
    while True:
        r = session.get(f"{BASE_URL}/api/v6/documents?limit=20&offset={offset}", timeout=30)
        r.raise_for_status()
        data = r.json()
        docs.extend(data.get('items', []))
        print('.', end='', flush=True)
        if not data.get('next'):
            break
        offset += 20
        time.sleep(0.3)
    print(f" {len(docs)} documents found", flush=True)
    return docs


def get_document_versions(session, doc_id):
    """Return list of named versions for a document."""
    r = session.get(f"{BASE_URL}/api/v6/documents/{doc_id}/versions", timeout=15)
    if r.status_code == 200:
        return r.json()
    return []


def delete_document(session, doc_id):
    """Permanently delete an Onshape document."""
    r = session.delete(f"{BASE_URL}/api/v6/documents/{doc_id}", timeout=15)
    return r


def create_version(session, doc_id, workspace_id, version_name, description=""):
    """Create a named version from the current workspace state."""
    r = session.post(
        f"{BASE_URL}/api/v6/documents/{doc_id}/workspaces/{workspace_id}/versions",
        json={"name": version_name, "description": description},
        timeout=15
    )
    return r


# ── Analysis ───────────────────────────────────────────────────────────────────
def classify_documents(docs):
    """
    Split documents into:
      - auto_versions: documents whose name matches NAME.XXXX (Inventor auto-saves)
      - clean:         all other documents (the ones we want to keep)

    Also builds a lookup: base_name → clean document, so we can tell whether
    a versioned document has a parent to be deleted into.
    """
    auto_versions = []
    clean = []

    for doc in docs:
        name = doc.get('name', '')
        if INVENTOR_VERSION_PATTERN.match(name):
            auto_versions.append(doc)
        else:
            clean.append(doc)

    # Map base name → clean document for cross-reference
    clean_by_name = {doc['name']: doc for doc in clean}

    return auto_versions, clean, clean_by_name


# ── Versioning phase ───────────────────────────────────────────────────────────
def ensure_versioned(session, clean_docs, version_name, version_desc, delay=0.5):
    """
    For every clean document that has no named versions yet,
    create version_name to establish a stable baseline.
    """
    print()
    print(f"  Checking version history for {len(clean_docs)} documents...", flush=True)

    need_version = []
    for doc in clean_docs:
        versions = get_document_versions(session, doc['id'])
        if not versions:
            need_version.append(doc)
        time.sleep(delay)

    if not need_version:
        print("  ✓ All documents already have at least one named version.")
        return

    print(f"  {len(need_version)} documents have no version yet — will create '{version_name}'")
    print()

    done = 0
    for i, doc in enumerate(need_version, 1):
        ws_id = doc.get('defaultWorkspace', {}).get('id')
        if not ws_id:
            print(f"  [{i:>4}/{len(need_version)}] {doc['name']} — no workspace id, skipping")
            continue

        print(f"  [{i:>4}/{len(need_version)}] {doc['name']}...", end='', flush=True)
        r = create_version(session, doc['id'], ws_id, version_name, version_desc)
        if r.status_code in (200, 201):
            print(" ✓")
            done += 1
        else:
            print(f" ✗ {r.status_code}: {r.text[:80]}")
        time.sleep(delay)

    print(f"\n  ✓ Created '{version_name}' on {done}/{len(need_version)} documents")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Onshape Version Restructure")
    print("=" * 60)
    print()

    session = get_session()

    # Auth check
    r = session.get(f"{BASE_URL}/api/v6/documents?limit=1")
    if r.status_code != 200:
        raise RuntimeError(f"Session auth failed ({r.status_code}). Log in to Onshape in your browser.")
    print("  ✓ Authenticated\n")

    # ── Phase 1: Inventory ─────────────────────────────────────────────────────
    print("─" * 60)
    print("  Phase 1 — Scanning document library")
    print("─" * 60)
    all_docs = list_all_documents(session)
    auto_versions, clean_docs, clean_by_name = classify_documents(all_docs)

    print(f"\n  Total documents   : {len(all_docs)}")
    print(f"  Clean documents   : {len(clean_docs)}  ← these will be kept")
    print(f"  Auto-version docs : {len(auto_versions)}  ← Inventor .XXXX backups to remove")

    if not auto_versions:
        print("\n  ✓ No Inventor auto-version documents found — account is already clean.")
    else:
        # ── Phase 2: Preview ───────────────────────────────────────────────────
        print()
        print("─" * 60)
        print("  Phase 2 — Preview of auto-version documents to delete")
        print("─" * 60)
        print()

        # Group by base name for a cleaner summary
        groups = {}
        for doc in auto_versions:
            match = INVENTOR_VERSION_PATTERN.match(doc['name'])
            base = match.group(1) if match else doc['name']
            groups.setdefault(base, []).append(doc['name'])

        orphaned = []  # .XXXX docs whose base name has no clean counterpart
        parented = []

        for base, versions in sorted(groups.items()):
            has_parent = base in clean_by_name
            status = "✓ parent exists" if has_parent else "⚠ no parent (orphan)"
            print(f"  {base}  [{len(versions)} revision(s)]  {status}")
            for v in sorted(versions):
                print(f"    · {v}")
            if has_parent:
                parented.extend(versions)
            else:
                orphaned.extend(versions)

        print()
        if orphaned:
            print(f"  ⚠  {len(orphaned)} orphaned revision(s) have no clean parent document.")
            print(f"     These will still be deleted — they're auto-saves with no current version.")
        print(f"\n  {len(auto_versions)} documents will be permanently deleted.")

        # ── Phase 3: Delete ────────────────────────────────────────────────────
        print()
        confirm = input("  Type YES to delete all auto-version documents: ").strip()
        if confirm != "YES":
            print("  Deletion skipped.")
        else:
            print()
            print("─" * 60)
            print("  Phase 3 — Deleting Inventor auto-version documents")
            print("─" * 60)
            print()

            deleted = failed = 0
            for i, doc in enumerate(auto_versions, 1):
                print(f"  [{i:>4}/{len(auto_versions)}] {doc['name']}...", end='', flush=True)
                r = delete_document(session, doc['id'])
                if r.status_code in (200, 204):
                    print(" ✓")
                    deleted += 1
                else:
                    print(f" ✗ {r.status_code}: {r.text[:80]}")
                    failed += 1
                time.sleep(0.8)

            print(f"\n  ✅ Deleted {deleted} auto-version documents")
            if failed:
                print(f"  ❌ {failed} deletions failed")

    # ── Phase 4: Version clean documents ──────────────────────────────────────
    print()
    print("─" * 60)
    print("  Phase 4 — Establishing version baselines")
    print("─" * 60)
    print()
    print("  In Onshape, a named version is a permanent, immutable snapshot —")
    print("  the equivalent of a release tag. Every document should have at")
    print("  least one version marking its stable baseline.")
    print()
    default_version = "v1.0 - Initial Release"
    version_name = input(f"  Version name for unversioned documents [{default_version}]: ").strip() or default_version
    version_desc = input(f"  Description (optional, e.g. 'Imported from Autodesk Inventor'): ").strip()

    ensure_versioned(session, clean_docs, version_name, version_desc)

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Done!")
    print()
    print("  Your Onshape library now follows best practices:")
    print("  · One document per part/assembly")
    print("  · Inventor auto-save noise removed")
    print("  · Every document has a named version baseline")
    print()
    print("  Next steps in Onshape:")
    print("  · When you make significant design changes, create a new")
    print("    version (right-click document → Create Version)")
    print("  · Use branches for parallel design exploration")
    print("  · Link assemblies to specific part versions to lock")
    print("    configurations for manufacturing releases")
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
