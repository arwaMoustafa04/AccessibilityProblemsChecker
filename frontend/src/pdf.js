// pdf.js renders the uploaded PDF in the finding viewer. It is loaded the first time a
// finding is opened, so the upload screen does not download it.
let loading = null

function pdfjs() {
  loading ??= Promise.all([
    import('pdfjs-dist'),
    import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
  ]).then(([lib, worker]) => {
    lib.GlobalWorkerOptions.workerSrc = worker.default
    return lib
  })
  return loading
}

// Opens a File (or Blob) as a pdf.js document.
export async function openPdf(file) {
  const { getDocument } = await pdfjs()
  const data = new Uint8Array(await file.arrayBuffer())
  return getDocument({ data }).promise
}
