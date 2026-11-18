"""Record write stamps must order writes even when the clock returns the same time twice (coarse Windows clock)."""
import contextlib, datetime, json
import pytest
import db, records, steps


class FrozenClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 19, 4, 0, 0, 123000)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    (tmp_path / 'workspace').mkdir(); (tmp_path / 'userdata').mkdir()
    monkeypatch.delenv('HMR_DB_KEY', raising=False)
    with contextlib.closing(db.connect(str(tmp_path / 'userdata' / 'hmr.db'))) as c:
        yield c


def test_stamps_are_strictly_increasing_when_the_clock_does_not_move(monkeypatch):
    monkeypatch.setattr(records.datetime, 'datetime', FrozenClock)
    stamps = [records._now() for _ in range(5)]
    assert stamps == sorted(set(stamps)) and len(stamps) == 5


def test_result_written_before_confirmed_list_is_older_even_in_the_same_clock_tick(conn, monkeypatch):
    monkeypatch.setattr(records.datetime, 'datetime', FrozenClock)
    records.put(conn, 1, 'MIMS interactions first.txt', b'first')
    records.put(conn, 1, 'confirmed_meds.json', json.dumps({'meds': [['aspirin', 'brand']]}).encode('utf-8'))
    assert records.stamp(conn, 1, 'MIMS interactions first.txt') < records.stamp(conn, 1, 'confirmed_meds.json')
