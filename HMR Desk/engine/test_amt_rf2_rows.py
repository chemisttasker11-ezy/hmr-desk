"""Synthetic RF2 text only. Never load licensed release data in CI."""
import io
import pytest
from medicine_data.amt import rf2_rows, MAX_RF2_LINE_CHARS


def test_literal_quotes_never_join_physical_rows_or_strip_concrete_quotes():
    text = ('id\tactive\tterm\r\n'
            '1\t1\t"leading unbalanced quote\r\n'
            '2\t1\t"literal quoted text"\r\n'
            '3\t0\tbackslash \\" stays literal\r\n')
    rows = list(rf2_rows(io.StringIO(text)))
    assert len(rows) == len(text.splitlines()) - 1 == 3
    assert rows[0]['term'] == '"leading unbalanced quote'
    assert rows[1]['term'] == '"literal quoted text"'
    assert rows[2]['term'] == 'backslash \\" stays literal'
    assert [r['id'] for r in rows] == ['1', '2', '3']


@pytest.mark.parametrize('row', ['1\t1\n', '1\t1\tx\textra\n', '\n', '1\t1\tx\ry\n', '1\t1\tx\x00y\n'])
def test_missing_extra_blank_or_control_rows_fail_closed(row):
    with pytest.raises(ValueError):
        list(rf2_rows(io.StringIO('id\tactive\tterm\n' + row)))


@pytest.mark.parametrize('header', ['', 'id\tid\tactive\n', 'id\t\tactive\n', 'id\tterm\n'])
def test_bad_headers_fail_closed(header):
    with pytest.raises(ValueError):
        list(rf2_rows(io.StringIO(header)))


def test_empty_field_is_preserved_not_missing_and_lf_supported():
    assert list(rf2_rows(io.StringIO('id\tactive\tterm\n1\t1\t\n')))[0]['term'] == ''


def test_physical_record_bound_refuses_oversize_no_truncation():
    with pytest.raises(ValueError):
        list(rf2_rows(io.StringIO('id\tactive\tterm\n1\t1\t' + 'x' * MAX_RF2_LINE_CHARS + '\n')))
