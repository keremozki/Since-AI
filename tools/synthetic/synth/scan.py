"""Scan imitation: raster at 150 dpi, grey, rotated 0.4 degrees, blurred, light noise, image-only PDF."""
import cv2
import numpy as np
import pymupdf

from . import data as D
from .docs import META_DATE, save
from .pen import MM

DPI, ANGLE = 150, 0.4


def scan(src_pdf, png_path, pdf_path):
    page = pymupdf.open(src_pdf)[0]
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    h, w = img.shape
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), ANGLE, 1.0)
    img = cv2.warpAffine(img, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=250)
    img = cv2.GaussianBlur(img, (0, 0), 0.7)
    rng = np.random.default_rng(D.SEED)
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 1.0 - 0.05 * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2)  # slight vignette
    out = img.astype(np.float32) * shade * 0.985 + rng.normal(0, 2.5, img.shape)
    spots = rng.random(img.shape) > 0.9996  # a few dust specks
    out[spots] -= 90
    out = np.clip(out, 0, 255).astype(np.uint8)
    cv2.imwrite(str(png_path), out, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    ok, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    doc = pymupdf.open()
    doc.set_metadata({"title": "ga-deck5-revA scan", "creator": "synthetic scanner", "producer": "PyMuPDF",
                      "creationDate": META_DATE, "modDate": META_DATE, "subject": D.SYNTH})
    new = doc.new_page(width=420 * MM, height=297 * MM)
    new.insert_image(new.rect, stream=jpg.tobytes())
    save(doc, pdf_path)
