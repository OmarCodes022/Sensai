"""The sandbox data folder: listing, adding, removing and example data over HTTP."""
import os
from urllib.parse import quote

import pytest

from sensai.settings import Settings
from sensai_web.datafiles import EXAMPLE_NAME


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "data"


def test_a_missing_folder_is_reported_and_created_on_the_first_file(web, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    page = web()
    listing = page.call("GET", "/api/run/data")[1]
    assert listing["exists"] is False and listing["files"] == [] and listing["dir"] == str(tmp_path / "data")
    assert listing["limits"] == {"file_mb": 10, "total_mb": 50, "types": [".csv", ".tsv", ".json", ".txt", ".md"]}
    status, body = page.call("PUT", "/api/run/data/figures.csv", {"text": "a,b\n1,2\n"})
    assert status == 200 and body["exists"] is True and body["files"] == [{"name": "figures.csv", "bytes": 8}]
    assert (tmp_path / "data" / "figures.csv").read_text() == "a,b\n1,2\n"


def test_added_files_are_visible_to_the_next_run_and_removed_ones_are_not(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    page.call("PUT", "/api/run/data/numbers.txt", {"text": "42"})
    assert page.call("POST", "/api/run", {"code": "print(open('numbers.txt').read())"})[1]["stdout"] == "42\n"
    page.call("DELETE", "/api/run/data/numbers.txt")
    body = page.call("POST", "/api/run", {"code": "import os\nprint(os.path.exists('numbers.txt'))"})[1]
    assert body["stdout"] == "False\n"


def test_a_file_can_be_replaced(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    page.call("PUT", "/api/run/data/a.json", {"text": "{}"})
    files = page.call("PUT", "/api/run/data/a.json", {"text": '{"x": 1}'})[1]["files"]
    assert files == [{"name": "a.json", "bytes": 8}]
    assert not [n for n in os.listdir(folder) if n.startswith(".upload")]  # No temporary file is left.


@pytest.mark.parametrize("name", ["../evil.csv", "a/b.csv", "..", ".hidden.csv", "x" * 101 + ".csv", "a b.csv",
                                  "evil.py", "evil.csv.py", "noext", "run.sh", "data.xlsx", "%2e%2e%2fx.csv"])
def test_bad_names_and_types_are_refused(web, folder, name):
    folder.mkdir()
    page = web(data_dir=str(folder))
    status, body = page.call("PUT", f"/api/run/data/{quote(name, safe='')}", {"text": "x"})
    assert status == 400 and body["error"]["code"] in ("bad_file_name", "bad_file_type")
    assert os.listdir(folder) == []


def test_only_text_within_the_sandbox_limits_is_accepted(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    assert page.call("PUT", "/api/run/data/a.csv", {"text": "a\x00b"})[1]["error"]["code"] == "not_text"
    assert page.call("PUT", "/api/run/data/a.csv", {"text": 5})[0] == 400
    assert page.call("PUT", "/api/run/data/a.csv", {})[0] == 400
    status, body = page.call("PUT", "/api/run/data/big.csv", {"text": "x" * (10 * 2**20 + 1)})
    assert status == 413 and body["error"]["code"] == "too_large"
    assert os.listdir(folder) == []


def test_the_whole_folder_is_capped_at_the_sandbox_total(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    for n in range(5):
        assert page.call("PUT", f"/api/run/data/part{n}.txt", {"text": "x" * (10 * 2**20)})[0] == 200
    status, body = page.call("PUT", "/api/run/data/part5.txt", {"text": "x"})
    assert status == 413 and "50 MB" in body["error"]["message"]
    assert page.call("PUT", "/api/run/data/part0.txt", {"text": "y"})[0] == 200  # Replacing frees its old size.


def test_a_symlink_target_is_never_written_through(web, folder, tmp_path):
    folder.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("keep")
    os.symlink(secret, folder / "link.txt")
    page = web(data_dir=str(folder))
    assert page.call("PUT", "/api/run/data/link.txt", {"text": "overwritten"})[0] == 400
    assert page.call("DELETE", "/api/run/data/link.txt")[0] == 404
    assert secret.read_text() == "keep"


def test_removing_a_file_that_is_not_there_is_a_404(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    assert page.call("DELETE", "/api/run/data/nope.csv")[1]["error"]["code"] == "not_found"
    assert page.call("DELETE", "/api/run/data/evil.py")[0] == 400


def test_example_data_is_added_once(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    status, body = page.call("POST", "/api/run/data/example")
    assert status == 200 and [f["name"] for f in body["files"]] == [EXAMPLE_NAME]
    out = page.call("POST", "/api/run", {"code": "import csv\nprint(len(list(csv.DictReader(open('engagement.csv')))))"})[1]
    assert out["stdout"] == "9\n"
    status, body = page.call("POST", "/api/run/data/example")
    assert status == 409 and body["error"]["code"] == "exists"


def test_data_changes_need_the_pages_own_origin(web, folder):
    folder.mkdir()
    page = web(data_dir=str(folder))
    evil = {"Origin": "http://evil.example"}
    assert page.call("PUT", "/api/run/data/a.csv", {"text": "x"}, headers=evil)[0] == 403
    assert page.call("DELETE", "/api/run/data/a.csv", headers=evil)[0] == 403
    assert page.call("POST", "/api/run/data/example", headers=evil)[0] == 403
    assert os.listdir(folder) == []


def test_the_data_folder_defaults_to_the_repository_placeholder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SENSAI_DATA_DIR", raising=False)
    assert Settings(_env_file=None).data_dir is None  # No ./data here.
    (tmp_path / "data").mkdir()
    assert Settings(_env_file=None).data_dir == "data"
    monkeypatch.setenv("SENSAI_DATA_DIR", "")
    assert not Settings(_env_file=None).data_dir  # Set but empty: the folder is switched off.
