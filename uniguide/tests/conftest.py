import os
from pathlib import Path

TEST_DATA_DIR = Path(__file__).resolve().parent / "_test_data"
TEST_DATA_DIR.mkdir(exist_ok=True)

# Must be set before uniguide.config is first imported anywhere.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DATA_DIR / 'test_uniguide.db'}")
os.environ.setdefault("CHROMA_PERSIST_DIR", str(TEST_DATA_DIR / "chroma"))
os.environ.setdefault("EMBEDDING_PROVIDER", "local")

import fitz  # noqa: E402  (PyMuPDF)
import pytest  # noqa: E402

from uniguide.db.database import Base, engine, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


def make_transcript_pdf(path, rows, headers=("Modulnummer", "Modulbezeichnung", "ECTS", "Note", "Semester")):
    """Draw a bordered table (PyMuPDF) that pdfplumber's line-based table
    detection can parse back out, so extract_grades_from_pdf has something
    real to test against without a live BOSS export.
    """
    col_widths = [70, 220, 50, 50, 60]
    x0, y0 = 50, 50
    row_height = 20
    n_rows = len(rows) + 1

    xs = [x0]
    for w in col_widths:
        xs.append(xs[-1] + w)
    y1 = y0 + row_height * n_rows

    doc = fitz.open()
    page = doc.new_page()

    for x in xs:
        page.draw_line((x, y0), (x, y1))
    y = y0
    for _ in range(n_rows + 1):
        page.draw_line((xs[0], y), (xs[-1], y))
        y += row_height

    def put_row(row_idx, values):
        y_text = y0 + row_idx * row_height + row_height - 6
        for i, val in enumerate(values):
            page.insert_text((xs[i] + 4, y_text), str(val), fontsize=9)

    put_row(0, headers)
    for i, row in enumerate(rows, start=1):
        put_row(i, row)

    doc.save(path)
    doc.close()
