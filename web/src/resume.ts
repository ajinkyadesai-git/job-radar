// Reading a visitor's resume happens here, in the browser. The file never leaves it:
// only the skill names found (and the years the visitor confirms) are sent to the API.

export interface SkillVocab {
  skills: { name: string; pattern: string }[];
  implies: Record<string, string[]>;
}

/** Skill name -> mentions, with the broader skills implied by specific ones (as on the server). */
export function findSkills(text: string, vocab: SkillVocab): string[] {
  const found = new Set<string>();
  for (const { name, pattern } of vocab.skills) {
    let rx: RegExp;
    try {
      rx = new RegExp(pattern, "i");
    } catch {
      continue; // a pattern this browser can't read is skipped, not fatal
    }
    if (rx.test(text)) found.add(name);
  }
  for (const name of [...found]) {
    for (const broader of vocab.implies[name] ?? []) found.add(broader);
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

/** The largest "N years" figure in the resume (a hint the visitor can change), or null. */
export function guessYears(text: string): number | null {
  const rx = /\b(\d{1,2})\s*\+?\s*(?:years|yrs)\b/gi;
  let best: number | null = null;
  for (const m of text.matchAll(rx)) {
    const n = Number(m[1]);
    if (n > 0 && n <= 30 && (best === null || n > best)) best = n;
  }
  return best;
}

const MAX_BYTES = 5 * 1024 * 1024;

/** Plain text from a PDF, Word (.docx) or text file. The readers load only when needed. */
export async function readResume(file: File): Promise<string> {
  if (file.size > MAX_BYTES) throw new Error("That file is over 5 MB; try a PDF or paste the text.");
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf") || file.type === "application/pdf") {
    const pdfjs = await import("pdfjs-dist");
    const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
    const doc = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
    const pages: string[] = [];
    for (let i = 1; i <= doc.numPages; i += 1) {
      const content = await (await doc.getPage(i)).getTextContent();
      pages.push(content.items.map((it) => ("str" in it ? it.str : "")).join(" "));
    }
    return pages.join("\n");
  }
  if (name.endsWith(".docx")) {
    const mammoth = await import("mammoth/mammoth.browser.js");
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    return result.value;
  }
  if (name.endsWith(".txt") || name.endsWith(".md") || file.type.startsWith("text/")) {
    return file.text();
  }
  throw new Error("Use a PDF, a Word (.docx) or a text file, or paste the text instead.");
}
