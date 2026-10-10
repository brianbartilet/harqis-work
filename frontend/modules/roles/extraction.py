"""Bounded attachment extraction. Extracted text is never shared automatically."""
from pathlib import Path
import shutil

SUPPORTED = {'.pdf', '.docx', '.md', '.markdown', '.txt', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}
MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 60000


def extract(path, name):
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError('Use PDF, DOCX, Markdown, text, or an image.')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Role attachments must be 20 MB or smaller.')
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('Upload an unencrypted PDF.')
        text = '\n\n'.join(f'Page {i+1}\n{page.extract_text() or ""}' for i, page in enumerate(reader.pages[:50]))
        truncated = len(reader.pages) > 50
    elif suffix == '.docx':
        from zipfile import ZipFile
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('The expanded document is too large.')
        from docx import Document
        doc = Document(path)
        text = '\n'.join([p.text for p in doc.paragraphs] + [' | '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows])
        truncated = False
    elif suffix in {'.md', '.markdown', '.txt'}:
        text, truncated = path.read_text('utf-8-sig'), False
    else:
        import pytesseract
        from PIL import Image
        if not shutil.which('tesseract'):
            windows = Path('C:/Program Files/Tesseract-OCR/tesseract.exe')
            if windows.exists():
                pytesseract.pytesseract.tesseract_cmd = str(windows)
        with Image.open(path) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError('Images must be smaller than 25 megapixels.')
            text = pytesseract.image_to_string(image, timeout=45)
        truncated = False
    if not text.strip() or (suffix == '.pdf' and not any(page.extract_text() for page in reader.pages[:50])):
        raise ValueError('No readable text found. For scanned PDFs, upload page images for OCR.')
    return {'text': text[:MAX_CHARS], 'truncated': truncated or len(text) > MAX_CHARS, 'status': 'ready'}
