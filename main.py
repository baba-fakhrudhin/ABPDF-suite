import os
import uuid
import io
from enum import Enum

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from PyPDF2 import PdfReader, PdfWriter
import pikepdf
from reportlab.pdfgen import canvas
from pdf2docx import Converter
from docx2pdf import convert

# -------------------- APP INIT --------------------

app = FastAPI(title="Document Converter Suite")
templates = Jinja2Templates(directory="templates")

app.add_middleware(SessionMiddleware, secret_key="supersecretkey123")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- PATHS --------------------

BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
USERS_FILE = "users.txt"

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -------------------- USER STORAGE --------------------

def read_users():
    users = {}
    if not os.path.exists(USERS_FILE):
        return users
    with open(USERS_FILE, "r") as f:
        for line in f:
            if line.strip():
                username, password = line.strip().split(" ")
                users[username] = password
    return users

def save_user(username: str, password: str):
    with open(USERS_FILE, "a") as f:
        f.write(f"{username} {password}\n")

def require_login(request: Request):
    user = request.session.get("user")
    if not user:
        return False
    return True

# -------------------- AUTH PAGES --------------------

@app.get("/login-page", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register-page", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...)):
    users = read_users()
    if username in users:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "User already exists"}
        )

    save_user(username, password)
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    users = read_users()

    if username not in users or users[username] != password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"}
        )

    request.session["user"] = username
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login-page", status_code=303)

# -------------------- HOME --------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not require_login(request):
        return RedirectResponse("/login-page", status_code=303)

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": request.session.get("user")}
    )

# -------------------- TOOL PAGES --------------------

def protected_page(template_name: str):
    async def page(request: Request):
        if not require_login(request):
            return RedirectResponse("/login-page", status_code=303)
        return templates.TemplateResponse(template_name, {"request": request})
    return page

app.get("/merge-page", response_class=HTMLResponse)(protected_page("merge.html"))
app.get("/split-page", response_class=HTMLResponse)(protected_page("split.html"))
app.get("/compress-page", response_class=HTMLResponse)(protected_page("compress.html"))
app.get("/watermark-page", response_class=HTMLResponse)(protected_page("watermark.html"))
app.get("/pdf-to-word-page", response_class=HTMLResponse)(protected_page("pdf_to_word.html"))
app.get("/word-to-pdf-page", response_class=HTMLResponse)(protected_page("word_to_pdf.html"))

# -------------------- FILE SAVE --------------------

async def save_upload_file(upload_file: UploadFile) -> str:
    file_id = str(uuid.uuid4())
    file_path = os.path.join(TEMP_DIR, f"{file_id}_{upload_file.filename}")
    contents = await upload_file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    return file_path

# -------------------- MERGE --------------------

@app.post("/merge")
async def merge_pdfs(
    request: Request,
    file1: UploadFile = File(None),
    file2: UploadFile = File(None),
    file3: UploadFile = File(None)
):
    if not require_login(request):
        return {"error": "Unauthorized"}

    files = [f for f in [file1, file2, file3] if f and f.filename]

    if len(files) < 2:
        return {"error": "Upload at least 2 files"}

    writer = PdfWriter()

    for file in files:
        contents = await file.read()
        reader = PdfReader(io.BytesIO(contents))
        for page in reader.pages:
            writer.add_page(page)

    output_path = os.path.join(OUTPUT_DIR, f"merged_{uuid.uuid4()}.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    return FileResponse(output_path, media_type="application/pdf", filename="merged.pdf")

# -------------------- SPLIT --------------------

@app.post("/split")
async def split_pdf(request: Request, file: UploadFile = File(...), pages: str = Form(...)):
    if not require_login(request):
        return {"error": "Unauthorized"}

    path = await save_upload_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()
    total_pages = len(reader.pages)

    try:
        page_numbers = set()

        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = map(int, part.split("-"))
                for p in range(start, end + 1):
                    if 1 <= p <= total_pages:
                        page_numbers.add(p)
            else:
                p = int(part)
                if 1 <= p <= total_pages:
                    page_numbers.add(p)

        for p in sorted(page_numbers):
            writer.add_page(reader.pages[p - 1])

        output_path = os.path.join(OUTPUT_DIR, f"split_{uuid.uuid4()}.pdf")

        with open(output_path, "wb") as f:
            writer.write(f)

        return FileResponse(output_path, media_type="application/pdf", filename="split.pdf")

    except:
        return {"error": "Invalid page format"}

# -------------------- COMPRESS --------------------

class CompressionLevel(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"

@app.post("/compress")
async def compress_pdf(request: Request, file: UploadFile = File(...), level: CompressionLevel = Form(CompressionLevel.moderate)):
    if not require_login(request):
        return {"error": "Unauthorized"}

    path = await save_upload_file(file)
    output_path = os.path.join(OUTPUT_DIR, f"compressed_{uuid.uuid4()}.pdf")

    with pikepdf.open(path) as pdf:
        pdf.remove_unreferenced_resources()
        pdf.save(
            output_path,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate
        )

    return FileResponse(output_path, media_type="application/pdf", filename="compressed.pdf")

# -------------------- WATERMARK --------------------

@app.post("/watermark")
async def watermark_pdf(
    request: Request,
    file: UploadFile = File(...),
    text: str | None = Form(None)
):
    if not require_login(request):
        return {"error": "Unauthorized"}

    path = await save_upload_file(file)
    reader = PdfReader(path)
    first_page = reader.pages[0]
    page_width = float(first_page.mediabox.width)
    page_height = float(first_page.mediabox.height)

    watermark_path = os.path.join(TEMP_DIR, f"wm_{uuid.uuid4()}.pdf")
    c = canvas.Canvas(watermark_path, pagesize=(page_width, page_height))

    if text:
        diagonal = (page_width**2 + page_height**2) ** 0.5
        font_size = int(diagonal / 18)

        c.saveState()
        c.setFont("Helvetica-Bold", font_size)
        c.setFillAlpha(0.15)
        c.translate(page_width / 2, page_height / 2)
        c.rotate(-45)
        c.drawCentredString(0, 0, text)
        c.restoreState()

    c.save()

    watermark_reader = PdfReader(watermark_path)
    watermark_page = watermark_reader.pages[0]
    writer = PdfWriter()

    for page in reader.pages:
        page.merge_page(watermark_page)
        writer.add_page(page)

    output_path = os.path.join(OUTPUT_DIR, f"watermarked_{uuid.uuid4()}.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    return FileResponse(output_path, media_type="application/pdf", filename="watermarked.pdf")
