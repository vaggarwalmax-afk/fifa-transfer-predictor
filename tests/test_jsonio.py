import os
import stat

from predictor.jsonio import read_json, write_json


def test_write_is_atomic_and_round_trips(tmp_path):
    path = tmp_path / "sub" / "data.json"
    write_json(path, {"name": "Ødegaard", "n": [1, 2]})
    assert read_json(path) == {"name": "Ødegaard", "n": [1, 2]}
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]  # no temp file left behind


def test_permissions_follow_umask_and_existing_file(tmp_path):
    old = os.umask(0o022)
    try:
        fresh = tmp_path / "fresh.json"
        write_json(fresh, {})
        assert stat.S_IMODE(fresh.stat().st_mode) == 0o644  # not mkstemp's 0600

        shared = tmp_path / "shared.json"
        shared.write_text("{}")
        os.chmod(shared, 0o664)
        write_json(shared, {"a": 1})
        assert stat.S_IMODE(shared.stat().st_mode) == 0o664
    finally:
        os.umask(old)
