# Onshape CAD Uploader

A lightweight Python tool for uploading CAD files directly into your [Onshape](https://www.onshape.com) account. Select files from your computer, choose a destination folder, and upload — no API key or quota required.

## Scripts

| Script | Auth method | Quota usage | Best for |
|---|---|---|---|
| `onshape_uploader.py` | Browser session (cookies) | None | Day-to-day use |
| `onshape_uploader_apikey.py` | API key (`.env`) | Yes (2,500 req/year) | Automated / headless use |

Both scripts have the same interactive UX — file picker, folder browser, document naming.

## Features

- **File picker UI** — select one or more CAD files via a native file dialog
- **Folder browser** — lists your Onshape folders and lets you choose a destination
- **Two auth methods** — browser session (no quota) or API key (for automation)
- **Multi-browser support** — works with Brave, Chrome, and Edge
- **Manual fallback** — if auto cookie-read fails, the tool walks you through copying cookies from DevTools
- **Auto-installs dependencies** — no setup required beyond Python itself

## Supported File Types

STEP, IGES, STL, Parasolid, ACIS, DXF, DWG, OBJ, SolidWorks (.sldprt / .sldasm), Inventor (.ipt / .iam), 3DXML, and more.

## Requirements

- Python 3.8+
- Dependencies are installed automatically on first run (`requests`, `browser-cookie3`)

**Browser session version** (`onshape_uploader.py`):
- A browser (Brave, Chrome, or Edge) logged into [cad.onshape.com](https://cad.onshape.com)

**API key version** (`onshape_uploader_apikey.py`):
- A `.env` file in the same folder containing your Onshape API credentials:
  ```
  ONSHAPE_ACCESS_KEY=your_access_key
  ONSHAPE_SECRET_KEY=your_secret_key
  ```
- Get API keys at [dev-portal.onshape.com/keys](https://dev-portal.onshape.com/keys)

## Usage

```bash
# Browser session version (recommended — no quota)
python onshape_uploader.py

# API key version
python onshape_uploader_apikey.py
```

Both tools follow the same steps:

1. Authenticate
2. Open a file picker — select one or more CAD files
3. Show your Onshape folders — pick a destination (or upload to root)
4. Ask for a document name for each file (defaults to the filename)
5. Upload and report results

## Authentication

**Browser session (`onshape_uploader.py`):** Reads your session cookies directly from your browser — the same cookies used when you browse Onshape normally. No API key setup required, and no annual quota limits.

If automatic cookie reading fails (common on some Windows setups due to permissions), the tool will display step-by-step instructions for copying your session cookies manually from the browser DevTools Network tab.

> **Tip:** If you see a permissions error, try running your terminal or VS Code as administrator.

**API key (`onshape_uploader_apikey.py`):** Uses HMAC-SHA256 signed requests with your Onshape API key. More portable (works without a browser) but counts against Onshape's 2,500 request/year quota on free plans.

## How It Works

Files are uploaded to Onshape's blob element endpoint, which triggers Onshape's CAD translation pipeline. Translated models typically appear in your document within 1–2 minutes.

## License

MIT — see [LICENSE](LICENSE)
