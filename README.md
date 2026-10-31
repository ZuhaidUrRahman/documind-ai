# DocuMind AI — All-in-One PDF Suite

A Flask MVP with a polished web UI for PDF chat, OCR, searchable PDF creation, summarization, translation/localization, audio transcription, video transcription, PDF-to-Word and PDF-to-Excel.

## 1. Requirements
- Python 3.10+ (tested design target: Python 3.12)
- OpenAI API key for AI chat, summarization, translation and transcription
- Tesseract OCR installed separately for OCR/searchable PDFs
- Internet access for API-backed AI features

## 2. Install on Windows PowerShell
Open PowerShell in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Add your API key to `.env`:
`OPENAI_API_KEY=your_real_key_here`

Do not share your `.env` or publish it to GitHub.

If you have an existing virtual environment, use its Python directly:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Install Tesseract OCR
Install the Windows build of Tesseract OCR. If it is not on PATH, set the full executable path in `.env`, for example:
`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`

Restart the Flask app after changing `.env`.

## 4. Run
```powershell
.\.venv\Scripts\python.exe app.py
```
Open `http://127.0.0.1:5000`.

## 5. Feature notes
- **Audio transcription:** uploads audio to the configured OpenAI transcription model.
- **Video transcription:** uses bundled imageio-ffmpeg to extract audio, then transcribes it. The MVP rejects extracted audio over 24 MB; long videos need chunking in a later version.
- **OCR:** requires both the Python `pytesseract` package and the separate Tesseract application.
- **Translation/localization:** model support varies by language; quality differs by language and subject.
- **PDF to Word:** extracts text; it does not preserve complex layout exactly.
- **PDF to Excel:** detects tables in text-based PDFs. It is not a general-purpose reconstruction engine for scanned tables.
- **PDF chat:** this starter stores document text in process memory. It is not a secure multi-user production RAG system and data is lost when the server restarts.
- **Uploads/outputs:** stored locally in `uploads/` and `outputs/`. Add authentication, quotas, file expiry/deletion, malware scanning and access controls before public deployment.

## 6. Suggested production hardening
Use a database and per-user document ownership, background jobs for large files, rate limits, antivirus scanning, HTTPS, CSRF protection, retention/deletion controls, request logging without document content, and a retrieval index that chunks PDFs and returns verified page citations.
