"""Generated synthetic PDFs: direct extraction, source hash, missing/corrupt/OCR cases."""
import hashlib
import fitz
import pytest
import local_referral_extraction


def pdf(path, paragraphs):
    doc = fitz.open()
    for text in paragraphs:
        page = doc.new_page()
        page.insert_text((60, 75), text, fontsize=10)
    doc.save(path)
    doc.close()


def test_multi_source_provenance_no_hallucinations(tmp_path):
    folder = tmp_path / 'Synthetic referral case'
    folder.mkdir()
    source = folder / 'referral.pdf'
    pdf(source, ['Synthetic HMR referral form. Medication history supplied for manual review. ' * 3,
                 'Synthetic pathology with unit mmol/L and dated sample. ' * 4])
    output = local_referral_extraction.extract(folder, folder / 'case-images')
    assert 'PAGE 1 (PDF TEXT' in output
    assert 'PAGE 2 (PDF TEXT' in output
    assert hashlib.sha256(source.read_bytes()).hexdigest() in output
    assert 'synthetic' in output.lower()
    assert 'UNCONFIRMED' in output
    assert source.is_file()


def test_missing_and_corrupt_pdf_do_not_create_case_or_invent_content(tmp_path):
    folder = tmp_path / 'empty'
    folder.mkdir()
    with pytest.raises(FileNotFoundError):
        local_referral_extraction.extract(folder, folder / 'case-images')
    (folder / 'referral.pdf').write_bytes(b'%PDF- damaged')
    with pytest.raises(ValueError, match='Unreadable|damaged'):
        local_referral_extraction.extract(folder, folder / 'case-images')
    assert not (folder / 'case.txt').exists()


def test_scan_fails_closed_without_ocr(tmp_path, monkeypatch):
    folder = tmp_path / 'scan'
    folder.mkdir()
    pdf(folder / 'scan.pdf', [''])  # a real blank PDF page
    class MissingOcr:
        def ocr_pdfs(self, paths): return {}
    import referral_entry
    monkeypatch.setattr(referral_entry, 'parser', lambda: MissingOcr())
    extracted = local_referral_extraction.extract(folder, folder / 'case-images')
    assert 'OCR UNAVAILABLE' in extracted and 'VIEW ORIGINAL PDF' not in extracted
    assert (folder / 'scan.pdf').is_file()
