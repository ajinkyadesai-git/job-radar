// The PDF worker, with the polyfills loaded first (a worker has its own globals).
import "./pdfPolyfills";
import "pdfjs-dist/legacy/build/pdf.worker.mjs";
