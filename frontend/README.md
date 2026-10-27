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

The API currently runs six checks: CHK-TITLE, CHK-LANG and CHK-HEADINGS (Person 3) and
CHK-SENSORY, CHK-COLOR and CHK-LINK (Person 2). CHK-NONTEXT and CHK-STRUCTURE
are shown as "not performed" and listed under Limitations. The results screen can
download the report PDF and the output PDF that `/process` returns.

In `npm run dev`, a dark "Preview" bar at the top lets you jump between the
screens (Upload, Upload + error, Processing, Results with sample data). It is not included in the
production build.

## Screens

1. **Upload**: drag-and-drop or file picker, file name and size, error message area, Analyze PDF button.
2. **Processing**: "Analyzing PDF…" with the steps Validating → Checking accessibility → Classifying findings.
3. **Results**: summary counts, finding cards, checks performed (with checks that did not run marked), limitations, the compliance disclaimer, and Analyze Another PDF.

The UI only displays what `/process` returns; it never decides accessibility itself.

## Files

- `src/App.jsx`: which screen is shown, plus the development preview bar
- `src/components/UploadScreen.jsx`, `ProcessingScreen.jsx`, `ResultsScreen.jsx`, `FindingCard.jsx`
- `src/data/checks.js`: the 8 agreed checks (same as `catalog.py` / `GET /checks`), used for display names
- `src/api.js`: `POST /process` call and the error messages for each `error_code`
- `src/data/mockResult.js`: sample response, used only by the dev preview bar
- `src/format.js`: file-size formatting and display labels
