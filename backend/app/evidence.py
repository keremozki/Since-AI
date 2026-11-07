"""Evidence pictures: the cited part of a page with the reading's box drawn on it."""
from __future__ import annotations

from pathlib import Path

import pymupdf

CROP_DPI = 200
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def image_as_pdf(data: bytes) -> bytes:
    """A one-page PDF of an image, in the page map's frame: points are pixels x 72 / the image's dpi, and 72 dpi
    when the image doesn't say. PyMuPDF's own conversion assumes 96 dpi then, which would shift every box."""
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    dpi = image.info.get("dpi", (72, 72))[0] or 72
    dpi = dpi if 10 <= dpi <= 1200 else 72
    width, height = image.size[0] * 72.0 / dpi, image.size[1] * 72.0 / dpi
    document = pymupdf.open()
    page = document.new_page(width=round(width, 2), height=round(height, 2))
    page.insert_image(page.rect, stream=data)
    return document.tobytes()


def _page(data: bytes, name: str, page: int) -> tuple[pymupdf.Document, pymupdf.Page]:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        document = pymupdf.open(stream=data, filetype="pdf")
    elif suffix in IMAGE_SUFFIXES:
        document = pymupdf.open(stream=image_as_pdf(data), filetype="pdf")
    else:
        raise ValueError(f"No pages to show in {name}.")
    if not 1 <= page <= len(document):
        raise ValueError(f"{name} has no page {page}.")
    return document, document[page - 1]


def crop_png(data: bytes, name: str, page: int, box: tuple[float, float, float, float], margin: float = 40.0) -> bytes:
    """A PNG of the box plus a margin, in the page's displayed frame, with the box outlined in red."""
    document, pdf_page = _page(data, name, page)
    x0, y0, x1, y1 = box
    rect = pymupdf.Rect(x0, y0, x1, y1)
    clip = pymupdf.Rect(x0 - margin, y0 - margin, x1 + margin, y1 + margin) & pdf_page.rect
    # Boxes are in the displayed (rotated) frame; drawing happens in the unrotated page frame.
    shape = pdf_page.new_shape()
    shape.draw_rect(rect * pdf_page.derotation_matrix)
    shape.finish(color=(0.85, 0.1, 0.1), width=1.2)
    shape.commit()
    zoom = CROP_DPI / 72
    pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
    document.close()
    return pixmap.tobytes("png")
