from pathlib import Path
import os
import subprocess
import uuid
import logging
import tempfile
import shutil

import pymupdf
import pytesseract
from PIL import Image, ImageOps
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, send_from_directory
from werkzeug.utils import secure_filename

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    import openpyxl
    import pdfplumber
except ImportError:
    openpyxl = None
    pdfplumber = None

BASE_DIR = Path(__file__).resolve().parent
FLASK_APP_DIR = BASE_DIR / "Flask App"
TEMPLATE_DIR = FLASK_APP_DIR / "Template"
STATIC_DIR = FLASK_APP_DIR / "Static"
UPLOAD_DIR = FLASK_APP_DIR / "Upload"
OUTPUT_DIR = FLASK_APP_DIR / "Output"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env", override=True)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

DOCUMENT_TEXTS = {}
logging.basicConfig(level=logging.INFO)

def force_tesseract():
    """Set Tesseract path for Windows or Linux (Render)."""
    configured = os.getenv("TESSERACT_CMD", "").strip().strip('"').strip("'")
    candidates = [
        configured,
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        shutil.which("tesseract"),
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            pytesseract.pytesseract.tesseract_cmd = str(Path(cand))
            return pytesseract.pytesseract.tesseract_cmd
    # Fallback
    pytesseract.pytesseract.tesseract_cmd = "tesseract"
    return "tesseract"

def get_openai():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or not OPENAI_AVAILABLE:
        return None
    return OpenAI(api_key=key)

def ai(messages):
    client = get_openai()
    if not client:
        raise RuntimeError("OpenAI key missing")
    r = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=0.3,
        max_tokens=1500,
    )
    return r.choices[0].message.content.strip()

def save_upload(fs):
    if not fs or not fs.filename:
        raise ValueError("No file")
    name = f"{Path(secure_filename(fs.filename) or 'file').stem[:40]}_{uuid.uuid4().hex[:8]}{Path(fs.filename).suffix.lower()}"
    dest = UPLOAD_DIR / name
    fs.save(dest)
    return dest

def ocr_image(img):
    force_tesseract()
    return pytesseract.image_to_string(img, config="--psm 3").strip()

def extract_text(path: Path):
    force_tesseract()
    ext = path.suffix.lower()
    if ext == ".pdf":
        pages = []
        with pymupdf.open(str(path)) as doc:
            for i, page in enumerate(doc, 1):
                text = page.get_text("text").strip()
                if not text:
                    try:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        text = ocr_image(img)
                    except Exception as e:
                        text = f"[OCR failed: {e}]"
                pages.append(f"[Page {i}]\n{text}")
        return "\n\n".join(pages)
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            return ocr_image(im)
    raise ValueError("Unsupported file")

@app.route("/")
def index():
    return render_template("index.html") if (TEMPLATE_DIR / "index.html").exists() else "API running"

@app.route("/api/health")
def health():
    try:
        cmd = force_tesseract()
        ver = subprocess.check_output([cmd, "--version"], text=True, timeout=10).splitlines()[0]
        ocr_ok = True
    except Exception as e:
        ver = str(e)
        ocr_ok = False
    return jsonify({"status": "ok", "ocr_configured": ocr_ok, "ocr_message": ver, "ai_configured": bool(os.getenv("OPENAI_API_KEY"))})

@app.route("/api/upload", methods=["POST"])
def upload():
    try:
        path = save_upload(request.files.get("file"))
        text = extract_text(path)
        DOCUMENT_TEXTS[path.name] = text
        return jsonify({"success": True, "document_id": path.name, "filename": path.name, "text": text, "characters": len(text)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/ocr", methods=["POST"])
def ocr():
    try:
        force_tesseract()
        path = save_upload(request.files.get("file"))
        text = extract_text(path)
        return jsonify({"success": True, "text": text, "characters": len(text)})
    except Exception as e:
        return jsonify({"success": False, "error": f"OCR could not run. {e}"}), 400

@app.route("/api/searchable-pdf", methods=["POST"])
def searchable_pdf():
    try:
        force_tesseract()
        path = save_upload(request.files.get("file"))
        ext = path.suffix.lower()
        out_name = f"searchable_{uuid.uuid4().hex[:8]}.pdf"
        out_path = OUTPUT_DIR / out_name

        if ext == ".pdf":
            with pymupdf.open(str(path)) as doc:
                pages = []
                for page in doc:
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    pages.append(pytesseract.image_to_pdf_or_hocr(img, extension="pdf"))
            out = pymupdf.open()
            for pb in pages:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pb)
                    tmp.flush()
                    out.insert_pdf(pymupdf.open(tmp.name))
                    Path(tmp.name).unlink(missing_ok=True)
            out.save(out_path)
            out.close()
        else:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                out_path.write_bytes(pytesseract.image_to_pdf_or_hocr(im, extension="pdf"))

        return jsonify({
            "success": True,
            "message": "Searchable PDF created.",
            "downloads": [{"url": f"/download/{out_name}", "label": "Download searchable PDF"}]
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not create searchable PDF. {e}"}), 400

@app.route("/api/summarize", methods=["POST"])
def summarize():
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text") or ""
        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400
        if get_openai():
            summary = ai([{"role": "user", "content": f"Summarize clearly:\n\n{text[:12000]}"}])
        else:
            summary = "OpenAI key not available."
        return jsonify({"success": True, "text": summary, "answer": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        question = data.get("question", "").strip()
        ids = data.get("document_ids") or []
        if not question or not ids:
            return jsonify({"success": False, "error": "Question and documents required"}), 400
        context = "\n\n".join(DOCUMENT_TEXTS.get(i, "") for i in ids)
        if get_openai():
            answer = ai([
                {"role": "system", "content": "Answer only from the document. Be concise."},
                {"role": "user", "content": f"Document:\n{context[:14000]}\n\nQuestion: {question}"}
            ])
        else:
            answer = "OpenAI key not configured."
        return jsonify({"success": True, "answer": answer})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/translate", methods=["POST"])
def translate():
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        target = data.get("target_language", "English")
        if not get_openai():
            return jsonify({"success": False, "error": "OpenAI key required"}), 400
        result = ai([{"role": "user", "content": f"Translate into {target}. Output only the translation:\n\n{text[:10000]}"}])
        return jsonify({"success": True, "text": result, "answer": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/transcribe/audio", methods=["POST"])
@app.route("/api/transcribe/video", methods=["POST"])
def transcribe():
    try:
        path = save_upload(request.files.get("file"))
        client = get_openai()
        if not client:
            return jsonify({"success": False, "error": "OpenAI key required"}), 400
        with open(path, "rb") as f:
            tr = client.audio.transcriptions.create(
                model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
                file=f,
                response_format="text"
            )
        text = tr if isinstance(tr, str) else getattr(tr, "text", str(tr))
        return jsonify({"success": True, "text": text, "answer": text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/convert/word", methods=["POST"])
def to_word():
    if not DocxDocument:
        return jsonify({"success": False, "error": "python-docx not installed"}), 500
    try:
        path = save_upload(request.files.get("file"))
        text = extract_text(path)
        doc = DocxDocument()
        doc.add_heading("Extracted Document", 0)
        for p in text.split("\n\n"):
            if p.strip():
                doc.add_paragraph(p.strip())
        out_name = f"converted_{uuid.uuid4().hex[:8]}.docx"
        doc.save(OUTPUT_DIR / out_name)
        return jsonify({
            "success": True,
            "message": "Word document created.",
            "downloads": [{"url": f"/download/{out_name}", "label": "Download DOCX"}]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/convert/excel", methods=["POST"])
def to_excel():
    if not openpyxl or not pdfplumber:
        return jsonify({"success": False, "error": "openpyxl or pdfplumber missing"}), 500
    try:
        path = save_upload(request.files.get("file"))
        wb = openpyxl.Workbook()
        ws = wb.active
        row = 1
        with pdfplumber.open(path) as pdf:
            for pn, page in enumerate(pdf.pages, 1):
                for table in page.extract_tables() or []:
                    ws.cell(row, 1, f"Page {pn}")
                    row += 1
                    for tr in table:
                        for c, cell in enumerate(tr or [], 1):
                            ws.cell(row, c, str(cell or ""))
                        row += 1
                    row += 2
        if row == 1:
            ws.cell(1, 1, "No tables found")
        out_name = f"tables_{uuid.uuid4().hex[:8]}.xlsx"
        wb.save(OUTPUT_DIR / out_name)
        return jsonify({
            "success": True,
            "message": "Excel file created.",
            "downloads": [{"url": f"/download/{out_name}", "label": "Download XLSX"}]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/download/<path:filename>")
def download(filename):
    safe = secure_filename(filename)
    if safe != filename:
        return jsonify({"error": "bad name"}), 400
    for folder in (OUTPUT_DIR, UPLOAD_DIR):
        cand = folder / safe
        if cand.is_file():
            return send_from_directory(str(folder), safe, as_attachment=True)
    return jsonify({"error": "not found"}), 404

@app.route("/api/debug")
def debug():
    return jsonify({
        "tesseract_cmd": str(getattr(pytesseract.pytesseract, "tesseract_cmd", "NOT SET")),
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "openai_key_starts_with_sk": str(os.getenv("OPENAI_API_KEY", "")).startswith("sk-"),
        "cwd": os.getcwd(),
    })

if __name__ == "__main__":
    try:
        cmd = force_tesseract()
        print("OCR ready:", subprocess.check_output([cmd, "--version"], text=True).splitlines()[0])
    except Exception as e:
        print("OCR unavailable:", e)
    print("OpenAI key loaded:", bool(os.getenv("OPENAI_API_KEY")))
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)