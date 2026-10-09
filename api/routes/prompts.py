"""Prompt upload and extraction endpoints for the experiment dashboard."""

import io
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, File, HTTPException, UploadFile


router = APIRouter(prefix="/prompts", tags=["Prompts"])
MAX_PROMPT_BYTES = 2 * 1024 * 1024
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_docx_prompt(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            document_xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(document_xml)
    except (KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError("The uploaded file is not a valid .docx document") from exc

    paragraphs = []
    for paragraph in root.findall(".//w:p", WORD_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS))
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


@router.post("/extract")
async def extract_prompt(file: UploadFile = File(...)):
    raw = await file.read(MAX_PROMPT_BYTES + 1)
    if len(raw) > MAX_PROMPT_BYTES:
        raise HTTPException(status_code=413, detail="Prompt file must be 2 MB or smaller.")

    filename = (file.filename or "").lower()
    try:
        if filename.endswith(".docx"):
            prompt = extract_docx_prompt(raw)
        elif filename.endswith((".txt", ".md")):
            prompt = raw.decode("utf-8-sig")
        else:
            raise HTTPException(status_code=400, detail="Upload a .docx, .txt, or .md prompt file.")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Text prompt files must use UTF-8 encoding.") from exc

    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="The uploaded prompt is empty.")
    return {"filename": file.filename, "prompt": prompt, "characters": len(prompt)}
