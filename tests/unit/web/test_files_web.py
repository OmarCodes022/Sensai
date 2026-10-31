"""File access in the page: status, /read, /save and the model's file tools, all through one check."""
import pytest

SETTINGS = ('{"permissions": {"allow": ["Read(./notes/**)", "Create(./drafts/**)", "Write(./drafts/**)"],'
            ' "deny": ["Read(./notes/private/**)"]}}')


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve()
    for d in ("notes/private", "drafts", ".sensai"):
        (root / d).mkdir(parents=True)
    (root / "notes" / "launch.md").write_text("Launch on 21 November", encoding="utf-8")
    (root / "secret.txt").write_text("secret", encoding="utf-8")
    (root / ".sensai" / "settings.json").write_text(SETTINGS)
    return root


def test_status_read_and_save(web, project):
    page = web(["Launch is on 21 November."])
    assert page.call("GET", "/api/files")[1] == {"on": True, "allow": 3, "deny": 1, "settings": ".sensai/settings.json"}
    assert page.call("GET", "/api/config")[1]["capabilities"]["file_access"] is True
    body = page.call("POST", "/api/files/read", {"path": "notes/launch.md"})[1]
    assert body == {"path": "notes/launch.md", "chars": 21, "text": "Launch on 21 November"}
    assert page.call("POST", "/api/files/save", {"path": "drafts/a.md"})[1]["error"]["code"] == "nothing_to_save"
    page.stream({"text": "When?"})
    assert page.call("POST", "/api/files/save", {"path": "drafts/a.md"})[1] == {"path": "drafts/a.md", "result": "Created"}
    assert page.call("POST", "/api/files/save", {"path": "drafts/a.md"})[1]["result"] == "Replaced"
    assert (project / "drafts" / "a.md").read_text() == "Launch is on 21 November.\n"


@pytest.mark.parametrize("path", ["secret.txt", "notes/private/x.md", "notes/../secret.txt", "/etc/hosts"])
def test_refused_reads_are_403_without_contents(web, project, path):
    status, body = web().call("POST", "/api/files/read", {"path": path})
    assert status == 403 and body["error"]["code"] == "permission_denied" and "secret\"" not in str(body)


def test_the_model_uses_the_file_tools(web, project):
    page = web(['{"tool":"create_file","arguments":{"path":"drafts/c.md","content":"caption"}}'], ["Saved."])
    page.stream({"text": "Save a caption draft"})
    assert (project / "drafts" / "c.md").read_text() == "caption"
    names = {t["name"] for t in page.call("GET", "/api/tools")[1]["items"]}
    assert {"read_file", "write_file", "create_file"} <= names


def test_without_settings_file_access_is_off(web, tmp_path):
    page = web()
    assert page.call("GET", "/api/files")[1] == {"on": False}
    assert page.call("POST", "/api/files/read", {"path": "x"})[1]["error"]["code"] == "file_access_off"
    assert "file_access" not in page.call("GET", "/api/config")[1]["capabilities"]
