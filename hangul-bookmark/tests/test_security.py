import pytest
from hangul_bookmark.backend import Hancom
from hangul_bookmark.errors import WriterError

def test_no_file_api_when_module_missing(monkeypatch):
    monkeypatch.delenv('HANGUL_ALLOW_MANUAL_APPROVAL',raising=False)
    h=object.__new__(Hancom); h.module=False
    with pytest.raises(WriterError,match='승인 창 반복'): h.open('never-opened.hwp')
    with pytest.raises(WriterError,match='승인 창 반복'): h.save('never-saved.hwpx')

def test_explicit_manual_diagnostic_opt_in(monkeypatch):
    monkeypatch.setenv('HANGUL_ALLOW_MANUAL_APPROVAL','1')
    h=object.__new__(Hancom); h.module=False; h.require_file_access()
