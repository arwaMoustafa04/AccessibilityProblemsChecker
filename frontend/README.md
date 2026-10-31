# Frontend (Phase 4 UI)

React + Vite UI for the PDF Accessibility Checker. **Analyze PDF** sends the file
to `POST /process` (`openapi.yaml`). A rejected file (missing, not a PDF, too large,
corrupted, encrypted, password-protected) returns to the upload screen with the
API's error; an accepted file shows the results the API returned.

```bash
# 1. Start the API (repo root), on port 8000
pip install -r requirements.txt
uvicorn main:app --port 8000

# 2. Start the UI
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # production files in frontend/dist
```

In dev, the UI calls `/api/...` and Vite forwards it to the API, so no CORS setup is
needed. To use the deployed system instead of a local one:

```bash
API_PROXY_TARGET=http://3.15.117.84/system npm run dev
```

To call an API directly (e.g. in a production build), set `VITE_API_URL` to its base
URL at build time; that server must then allow CORS from the UI's origin.

The API runs all eight agreed checks. Each finding card shows the issue, its result
(**Fail** or **Needs Review**), its location (page, or e.g. "Whole document"), the
check, its status, the PDF object it refers to (e.g. `Catalog/StructTreeRoot/K[0]/K[0]`),
the details and, when the API gives one, a suggested fix. Checks Performed lists how
many findings each check produced; a check the API did not run is shown as "not
performed" and listed under Limitations. The results screen can
download the report PDF and the output PDF that `/process` returns.

## Screens

1. **Upload**: drag-and-drop or file picker, file name and size, error message area, Analyze PDF button.
2. **Processing**: "Analyzing PDF…" with the steps Validating → Checking accessibility → Classifying findings.
3. **Results**: summary counts, finding cards (issue, result, location, PDF object, status), checks performed (with checks that did not run marked), limitations, the compliance disclaimer, the downloads, and Analyze Another PDF.
4. **PDF viewer** (side panel): click a finding (or its **Show in PDF** button) to see the
   uploaded PDF at that finding's page, with its position highlighted when the API gives
   one (`location.bbox`). Findings without a position show the page only; whole-document
   findings say so. Escape or × closes it. On narrow screens it covers the screen.

Downloads: **Download Report PDF** (`<file>_AccessibilityReport.pdf`), the output PDF, and
**Download Fixed PDF + Report (ZIP)** (`<file>_AccessibilityResults.zip` with both PDFs,
built in the browser). Until automatic repair is on, the output PDF is the uploaded file.

The UI only displays what `/process` returns; it never decides accessibility itself.

## Files

- `src/App.jsx`: which screen is shown
- `src/components/UploadScreen.jsx`, `ProcessingScreen.jsx`, `ResultsScreen.jsx`, `FindingCard.jsx`
- `src/components/PdfViewer.jsx`: the side panel that renders a page and highlights `location.bbox`
- `src/pdf.js`: loads pdf.js (only when a finding is first opened)
- `src/data/checks.js`: the 8 agreed checks (same as `catalog.py` / `GET /checks`), used for display names
- `src/api.js`: `POST /process` call, the error messages for each `error_code`, and the PDF/ZIP downloads
- `src/format.js`: file-size formatting and display labels
