from kilnmcp.pdf import md_to_pdf

def test_md_to_pdf(tmp_path):
    md = tmp_path / "batch_T.md"
    md.write_text("# Batch report T\n\n> **SAMPLE/SYNTHETIC DATA**\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    out = md_to_pdf(md)
    b = open(out, "rb").read()
    assert out.endswith("batch_T.pdf") and b.startswith(b"%PDF") and len(b) > 1000
