"""Markdown batch report -> PDF (pure Python: markdown -> HTML -> xhtml2pdf).

  python -m kilnmcp.pdf reports/batch_SYN-0001.md          # writes reports/batch_SYN-0001.pdf
"""
from __future__ import annotations
import sys
from pathlib import Path

CSS = """
@page { size: A4; margin: 1.6cm; @frame footer { -pdf-frame-content: foot; bottom: 0.6cm; height: 0.8cm; left: 1.6cm; right: 1.6cm; } }
body { font-family: Helvetica; font-size: 9pt; }
h1 { font-size: 16pt; } h2 { font-size: 12pt; margin-top: 10pt; }
table { border: 0.5pt solid #888; } td, th { padding: 2pt; border: 0.5pt solid #888; }
th { background-color: #eee; } blockquote { color: #a00; } pre, code { font-family: Courier; font-size: 8pt; }
"""
FOOT = '<div id="foot" style="font-size:7pt;color:#a00">SAMPLE/SYNTHETIC DATA - dMRV-style DRAFT - NOT CERTIFIED - page <pdf:pagenumber/></div>'

def md_to_pdf(md_path, pdf_path=None) -> str:
    import markdown
    from xhtml2pdf import pisa
    md_path = Path(md_path)
    pdf_path = Path(pdf_path) if pdf_path else md_path.with_suffix(".pdf")
    body = markdown.markdown(md_path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{FOOT}{body}</body></html>"
    with open(pdf_path, "wb") as f:
        res = pisa.CreatePDF(html, dest=f, encoding="utf-8")
    if res.err:
        raise RuntimeError(f"PDF generation failed ({res.err} errors)")
    return str(pdf_path)

if __name__ == "__main__":
    for a in sys.argv[1:] or ["reports/batch_SYN-0001.md"]:
        print(md_to_pdf(a))
