# Onshape CAD Uploader

A lightweight Python tool for uploading CAD files directly into your [Onshape](https://www.onshape.com) account. Select files from your computer, choose a destination folder, and upload — no API key or quota required.

## Features

- **File picker UI** — select one or more CAD files via a native file dialog
- **Folder browser** — lists your Onshape folders and lets you choose a destination
- **No API key needed** — authenticates via your existing browser session
- **Multi-browser support** — works with Brave, Chrome, and Edge
- **Manual fallback** — if auto cookie-read fails, the tool walks you through copying cookies from DevTools
- **Auto-installs dependencies** — no setup required beyond Python itself

## Supported File Types

STEP, IGES, STL, Parasolid, ACIS, DXF, DWG, OBJ, SolidWorks (.sldprt / .sldasm), Inventor (.ipt / .iam), 3DXML, and more.

## Requirements

- Python 3.8+
- A browser (Brave, Chrome, or Edge) logged into [cad.onshape.com](https://cad.onshape.com)
- Dependencies are installed automatically on first run (`requests`, `browser-cookie3`)

## Usage

```bash
python onshape_uploader.py
```

The tool will:

1. Authenticate using your active Onshape browser session
2. Open a file picker — select one or more CAD files
3. Show your Onshape folders — pick a destination (or upload to root)
4. Ask for a document name for each file (defaults to the filename)
5. Upload and report results

## Authentication

This tool reads your session cookies directly from your browser — the same cookies used when you browse Onshape normally. This means:

- No API key setup required
- No annual quota limits (Onshape's REST API key quota is 2,500 requests/year)
- Works as long as you are logged in to Onshape in your browser

If automatic cookie reading fails (common on some Windows setups due to permissions), the tool will display step-by-step instructions for copying your session cookies manually from the browser DevTools Network tab.

> **Tip:** If you see a permissions error, try running your terminal or VS Code as administrator.

## How It Works

Onshape's web app and its REST API share the same session infrastructure. By reading the `XSRF-TOKEN` cookie from your browser and forwarding it as the `X-XSRF-TOKEN` request header, this tool can make authenticated API calls on your behalf — identical to what the Onshape web app does internally.

Files are uploaded to Onshape's blob element endpoint, which triggers Onshape's CAD translation pipeline. Translated models typically appear in your document within 1–2 minutes.

## License

MIT — see [LICENSE](LICENSE)
