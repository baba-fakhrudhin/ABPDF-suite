import os
import uuid
import io
from enum import Enum

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from PyPDF2 import PdfReader, PdfWriter
import pikepdf
from reportlab.pdfgen import canvas
from pdf2docx import Converter
from docx2pdf import convert

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="Document Converter Suite")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/merge-page", response_class=HTMLResponse)
async def merge_page(request: Request):
    return templates.TemplateResponse("merge.html", {"request": request})

@app.get("/split-page", response_class=HTMLResponse)
async def split_page(request: Request):
    return templates.TemplateResponse("split.html", {"request": request})

@app.get("/compress-page", response_class=HTMLResponse)
async def compress_page(request: Request):
    return templates.TemplateResponse("compress.html", {"request": request})

@app.get("/watermark-page", response_class=HTMLResponse)
async def watermark_page(request: Request):
    return templates.TemplateResponse("watermark.html", {"request": request})

@app.get("/pdf-to-word-page", response_class=HTMLResponse)
async def pdf_to_word_page(request: Request):
    return templates.TemplateResponse("pdf_to_word.html", {"request": request})

@app.get("/word-to-pdf-page", response_class=HTMLResponse)
async def word_to_pdf_page(request: Request):
    return templates.TemplateResponse("word_to_pdf.html", {"request": request})

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    return FileResponse(file_path, media_type="application/pdf", filename="compressed.pdf")

class CompressionLevel(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


async def save_upload_file(upload_file: UploadFile) -> str:
    file_id = str(uuid.uuid4())
    file_path = os.path.join(TEMP_DIR, f"{file_id}_{upload_file.filename}")
    contents = await upload_file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    return file_path

@app.post("/merge")
async def merge_pdfs(
    file1: UploadFile = File(None),
    file2: UploadFile = File(None),
    file3: UploadFile = File(None)
):
    files = [file1, file2, file3]
    files = [f for f in files if f and f.filename != ""]

    if len(files) < 2:
        return {"error": "Please upload at least 2 PDF files"}

    writer = PdfWriter()

    try:
        for file in files:
            contents = await file.read()
            reader = PdfReader(io.BytesIO(contents))
            for page in reader.pages:
                writer.add_page(page)

        output_path = os.path.join(OUTPUT_DIR, f"merged_{uuid.uuid4()}.pdf")

        with open(output_path, "wb") as f:
            writer.write(f)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename="merged.pdf"
        )

    except Exception as e:
        return {"error": f"Merge failed: {str(e)}"}

import os

PORT = int(os.environ.get("PORT", 10000))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)

@app.post("/split")
async def split_pdf(
    file: UploadFile = File(...),
    pages: str = Form(...)
):
    """
    pages examples:
    1-3
    5
    1,3,5
    2-4,6
    """

    path = await save_upload_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()

    total_pages = len(reader.pages)

    try:
        page_numbers = set()

        parts = pages.split(",")

        for part in parts:
            part = part.strip()

            if "-" in part:
                start, end = part.split("-")
                start = int(start)
                end = int(end)

                if start < 1 or end > total_pages:
                    return {"error": "Page range out of bounds"}

                for p in range(start, end + 1):
                    page_numbers.add(p)

            else:
                p = int(part)
                if p < 1 or p > total_pages:
                    return {"error": f"Page {p} out of bounds"}
                page_numbers.add(p)

        for p in sorted(page_numbers):
            writer.add_page(reader.pages[p - 1])

        output_path = os.path.join(OUTPUT_DIR, f"split_{uuid.uuid4()}.pdf")

        with open(output_path, "wb") as f:
            writer.write(f)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename="split.pdf"
        )

    except Exception as e:
        return {"error": f"Invalid page format. Example: 1-3 or 1,3,5. Error: {str(e)}"}
@app.post("/compress")
async def compress_pdf(
    file: UploadFile = File(...),
    level: CompressionLevel = Form(CompressionLevel.moderate)
):
    if not file.filename.lower().endswith(".pdf"):
        return {"error": "Only PDF files are supported"}

    path = await save_upload_file(file)
    output_path = os.path.join(OUTPUT_DIR, f"compressed_{uuid.uuid4()}.pdf")

    try:
        original_size = os.path.getsize(path)

        with pikepdf.open(path) as pdf:

            pdf.remove_unreferenced_resources()

            if level == CompressionLevel.low:
                quality_factor = 90
            elif level == CompressionLevel.moderate:
                quality_factor = 70
            else:
                quality_factor = 40

            # Force stream compression
            pdf.save(
                output_path,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate
            )

        compressed_size = os.path.getsize(output_path)

        return {
            "success": True,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "download_url": f"/download/{os.path.basename(output_path)}"
        }

    except Exception as e:
        return {"error": f"Compression failed: {str(e)}"}

@app.post("/watermark")
async def add_watermark(
    file: UploadFile = File(...),
    text: str | None = Form(None),
    image: UploadFile = File(None)
):
    path = await save_upload_file(file)

    reader = PdfReader(path)
    first_page = reader.pages[0]
    page_width = float(first_page.mediabox.width)
    page_height = float(first_page.mediabox.height)

    watermark_path = os.path.join(TEMP_DIR, f"watermark_{uuid.uuid4()}.pdf")
    c = canvas.Canvas(watermark_path, pagesize=(page_width, page_height))

    if image and image.content_type.startswith("image/"):
        img_path = await save_upload_file(image)
        c.saveState()
        c.setFillAlpha(0.2)
        img_width = page_width * 0.6
        img_height = page_height * 0.6
        c.drawImage(
            img_path,
            (page_width - img_width) / 2,
            (page_height - img_height) / 2,
            width=img_width,
            height=img_height,
            preserveAspectRatio=True,
            mask='auto'
        )
        c.restoreState()

    elif text and text.strip() != "":
        diagonal = (page_width**2 + page_height**2) ** 0.5
        font_size = int(diagonal / 18)

        c.saveState()
        c.setFont("Helvetica-Bold", font_size)
        c.setFillAlpha(0.18)

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

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename="watermarked.pdf"
    )


@app.post("/word-to-pdf")
async def word_to_pdf(file: UploadFile = File(...)):
    path = await save_upload_file(file)

    if not path.lower().endswith(".docx"):
        return {"error": "Only .docx files are supported"}

    output_path = os.path.join(OUTPUT_DIR, f"{uuid.uuid4()}.pdf")

    try:
        convert(path, output_path)
    except Exception as e:
        return {"error": f"Conversion failed: {str(e)}"}

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename="converted.pdf"
    )

@app.post("/pdf-to-word")
async def pdf_to_word(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return {
            "error": "Invalid file type. Only .pdf files are supported."
        }

    path = await save_upload_file(file)
    output_path = os.path.join(OUTPUT_DIR, f"{uuid.uuid4()}.docx")

    try:
        cv = Converter(path)
        cv.convert(output_path)
        cv.close()
    except Exception as e:
        return {
            "error": f"PDF to Word conversion failed. Ensure the PDF is not corrupted and contains selectable text. Details: {str(e)}"
        }

    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="converted.docx"
    )
