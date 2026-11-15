"""Turn uploaded files into text and group them into applications."""
import io
import re

DOC_TYPES = {
    "cover_letter": ["cover", "letter", "motivation"],
    "publications": ["publication", "papers", "bibliography", "pubs"],
    "research_statement": ["research_statement", "research-statement", "research statement", "researchstatement"],
    "teaching_statement": ["teaching_statement", "teaching-statement", "teaching statement", "teachingstatement"],
    "cv": ["cv", "resume", "résumé", "curriculum", "vitae"],
}
DOC_LABELS = {"cv": "CV", "cover_letter": "Cover letter", "publications": "Publication list",
              "research_statement": "Research statement", "teaching_statement": "Teaching statement", "other": "Other document"}


def extract_text(filename, data: bytes):
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == "docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if ext in ("txt", "md", "text"):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f".{ext or '?'} files are not supported. Use PDF, DOCX or TXT.")


def doc_type(filename):
    n = filename.lower()
    for t, kws in DOC_TYPES.items():
        if any(k in n for k in kws):
            return t
    return "cv"


def applicant_key(filename):
    """'omar_farouk_cover_letter.pdf' -> 'omar farouk'. Files sharing a key belong to one application."""
    n = filename.rsplit("/", 1)[-1]
    n = re.sub(r"\.[^.]+$", "", n).lower()
    for kws in DOC_TYPES.values():
        for k in sorted(kws, key=len, reverse=True):
            n = n.replace(k, " ")
    n = re.sub(r"\b(statement|list|final|v\d+|copy)\b", " ", n)
    n = re.sub(r"[^a-z0-9؀-ۿ]+", " ", n).strip()
    return n


def group_files(files):
    """files: [(relative_path, bytes)]. Folder name wins over file name when present."""
    groups = {}
    for path, data in files:
        parts = path.replace("\\", "/").split("/")
        key = parts[-2].lower() if len(parts) > 1 else applicant_key(parts[-1])
        groups.setdefault(key or "applicant", []).append((parts[-1], data))
    return groups


def clean(text):
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
