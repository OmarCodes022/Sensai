"""chat.saved_sessions: session IDs, profile file and block, titles, recorder."""

import json
import re
import sqlite3

import pytest

from fakes import FakeClient, InterruptingConnection
from sensai.chat import saved_sessions
from sensai.chat.saved_sessions import (
    ID_ALPHABET,
    SessionRecorder,
    fallback_title,
    load_profile_file,
    new_session_id,
    profile_block,
)
from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import SessionSnapshot
from sensai.core.errors import LLMError
from sensai.memory import sqlite_store
from sensai.memory.sqlite_store import StorageError, StorageRepository

ID = re.compile(f"^[{ID_ALPHABET}]{{6}}$")


def test_session_ids_use_unambiguous_alphabet_and_retry_on_collision(monkeypatch):
    assert not set("ilo01") & set(ID_ALPHABET)
    assert all(ID.match(new_session_id(lambda _: False)) for _ in range(200))
    picks = iter("aaaaaa" "aaaaaa" "k7f2qa")
    monkeypatch.setattr(saved_sessions.secrets, "choice", lambda alphabet: next(picks))
    seen = []
    assert new_session_id(lambda sid: seen.append(sid) or sid == "aaaaaa") == "k7f2qa"
    assert seen == ["aaaaaa", "aaaaaa", "k7f2qa"]


def test_profile_file_is_stripped_ordered_and_rendered_in_french(tmp_path):
    path = tmp_path / "profil.json"
    path.write_text(json.dumps({" ton ": " direct ", "public": "créatrices mode"}), encoding="utf-8")
    preferences = load_profile_file(path)
    assert list(preferences.items()) == [("ton", "direct"), ("public", "créatrices mode")]
    assert profile_block(preferences) == (
        "Profil de la créatrice (instructions personnalisées) :\n"
        "- ton : direct\n- public : créatrices mode"
    )
    assert profile_block({}) == ""
    path.write_text("{}", encoding="utf-8")
    assert load_profile_file(path) == {}


@pytest.mark.parametrize("contents,error,match", [
    (b"[]", ValueError, "JSON object"),
    (b'"text"', ValueError, "JSON object"),
    (b'{"": "x"}', ValueError, "nonempty"),
    (b'{"  ": "x"}', ValueError, "nonempty"),
    (b'{"ton": 1}', ValueError, "nonempty string"),
    (b'{"ton": null}', ValueError, "nonempty string"),
    (b'{"ton": " \\n"}', ValueError, "nonempty string"),
    (b'{"ton": "a", " ton": "b"}', ValueError, "duplicate profile key: ton"),
    (b"{bad", ValueError, None),
    (b"\xff\xfe", ValueError, None),
])
def test_invalid_profile_files_raise_clear_errors(tmp_path, contents, error, match):
    path = tmp_path / "profil.json"
    path.write_bytes(contents)
    with pytest.raises(error, match=match):
        load_profile_file(path)


def test_unreadable_profile_files_raise_oserror(tmp_path):
    with pytest.raises(OSError):
        load_profile_file(tmp_path / "missing.json")
    with pytest.raises(OSError):
        load_profile_file(tmp_path)


def test_fallback_title_uses_collapsed_first_line_truncated_to_40():
    assert fallback_title("\n  Écris   une\tlégende \nsecond line") == "Écris une légende"
    long = "Prépare un calendrier éditorial complet pour le mois prochain"
    title = fallback_title(long)
    assert len(title) == 40 and title.endswith("…") and long.startswith(title[:-1])
    assert fallback_title("x" * 40) == "x" * 40
    assert fallback_title("x" * 41) == "x" * 39 + "…"
    assert fallback_title("   ") == ""


def test_profile_block_skips_blank_stored_entries():
    assert profile_block({" ": "x", "vide": "  \n", "ton": "direct"}) == (
        "Profil de la créatrice (instructions personnalisées) :\n- ton : direct")
    assert profile_block({"": "", " ": "\t"}) == ""


@pytest.mark.parametrize("reply", [
    "Titre\x85suite", "Titre\vsuite", "Titre\x0csuite", "Ti\u2028tre", "Titre\x00",
    "Titre\x1b[31m", "Titre\x7f", "Plan\u00a0: ligne un\nligne deux",
])
def test_title_must_be_one_printable_line(real_titles, reply):
    assert saved_sessions.generate_title(FakeClient([reply]), "m", "q", "a") is None


@pytest.mark.parametrize("reply,expected", [
    ("Plan\u00a0: lancement d'automne", "Plan : lancement d'automne"),
    ("Idées de légendes\u202f!", "Idées de légendes !"),
    ("«\u00a0Calendrier éditorial\u00a0»", "Calendrier éditorial"),
    ("Brief\u202f: été\u202f?", "Brief : été ?"),
    ("Titre\tà  revoir", "Titre à revoir"),
    ("x" * 30 + "\u00a0\u00a0" + "y" * 29, "x" * 30 + " " + "y" * 29),
])
def test_french_typography_spaces_are_normalised_in_titles(real_titles, reply, expected):
    assert saved_sessions.generate_title(FakeClient([reply]), "m", "q", "a") == expected


@pytest.mark.parametrize("reply,expected", [
    (["Calendrier ", "éditorial d'automne\n"], "Calendrier éditorial d'automne"),
    (['  "Plan de lancement"  '], "Plan de lancement"),
    (["«Légendes Instagram»"], "Légendes Instagram"),
    ([""], None), (["  \n "], None), (['""'], None),
    (["Ligne un\nLigne deux"], None), (["x" * 61], None), (["x" * 60], "x" * 60),
    ([LLMError("down")], None), (["Partial", LLMError("broken")], None),
    (["Partial", OperationCancelled("operation cancelled")], None),
    (["Partial", OperationTimedOut("operation timed out")], None),
])
def test_generate_title_validates_reply_from_a_separate_request(real_titles, reply, expected):
    client = FakeClient(reply)
    title = saved_sessions.generate_title(client, "model", "Bonjour", "Salut !", CancellationToken())
    assert title == expected
    [(model, request)] = client.requests
    assert model == "model"
    assert [m.role for m in request] == ["system", "user"]
    assert request[0].content == saved_sessions.TITLE_PROMPT
    assert "3 à 6 mots" in request[0].content and "sans guillemets" in request[0].content
    assert request[1].content == "Message : Bonjour\n\nRéponse : Salut !"


def test_generate_title_honours_cancellation_and_deadline(real_titles):
    cancelled = CancellationToken()
    cancelled.cancel()
    assert saved_sessions.generate_title(FakeClient(["Titre"]), "m", "q", "a", cancelled) is None
    expired = CancellationToken(deadline=0.0)
    assert saved_sessions.generate_title(FakeClient(["Titre"]), "m", "q", "a", expired) is None
    stop = iter([False, True])
    late = CancellationToken(cancel_requested=lambda: next(stop, True))
    assert saved_sessions.generate_title(FakeClient(["Ti", "tre"]), "m", "q", "a", late) is None


class FailingStore:
    def __init__(self, store, failures):
        self.store, self.failures, self.saves = store, list(failures), []

    def save(self, snapshot):
        failure = self.failures.pop(0) if self.failures else None
        if failure:
            raise failure
        self.saves.append(snapshot)
        self.store.save(snapshot)

    def set_title(self, session_id, title):
        self.store.set_title(session_id, title)


def completed_session(*turns):
    session = ChatSession(FakeClient(*([answer] for _, answer in turns)), "m", "System")
    for question, _ in turns:
        list(session.send(question))
    return session


def test_recorder_reports_failures_and_next_save_has_full_history(tmp_path):
    written = []
    with StorageRepository(tmp_path / "db.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        store = FailingStore(sessions, [StorageError("disk full"), sqlite3.OperationalError("locked")])
        titles = []
        recorder = SessionRecorder(store, "k7f2qa", "analyse", write=written.append,
                                   titler=lambda q, a: titles.append((q, a)) or "Titre généré")
        recorder.after_turn(completed_session(("Q1", "A1")))
        recorder.persona_changed("redaction")
        recorder.after_turn(completed_session(("Q1", "A1"), ("Q2", "A2")))
        assert written == ["error: session not saved: disk full", "error: session not saved: locked"]
        assert sessions.list() == () and titles == []
        session = completed_session(("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3"))
        recorder.after_turn(session)
        assert [m.content for m in session.messages] == ["System", "Q1", "A1", "Q2", "A2", "Q3", "A3"]
        assert sessions.load("k7f2qa") == SessionSnapshot(
            "k7f2qa", tuple(session.messages[1:]), "redaction")
        assert titles == [("Q1", "A1")]
        assert [s.title for s in sessions.list()] == ["Titre généré"]
        recorder.persona_changed("analyse")
        assert sessions.load("k7f2qa").persona_id == "analyse"
        recorder.after_turn(session)
        assert titles == [("Q1", "A1")] and len(written) == 2


def test_recorder_falls_back_and_does_not_save_persona_before_first_turn(tmp_path):
    with StorageRepository(tmp_path / "db.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        recorder = SessionRecorder(sessions, "k7f2qa", titler=lambda q, a: None)
        recorder.persona_changed("analyse")
        assert sessions.list() == ()
        recorder.after_turn(completed_session(("Écris  une\nlégende", "Voici")))
        assert sessions.load("k7f2qa").persona_id == "analyse"
        assert [s.title for s in sessions.list()] == ["Écris une"]


class TitleFailingStore:
    def __init__(self, store, failures):
        self.store, self.failures, self.titles = store, list(failures), []

    def save(self, snapshot):
        self.store.save(snapshot)

    def set_title(self, session_id, title):
        self.titles.append(title)
        if self.failures:
            raise self.failures.pop(0)
        self.store.set_title(session_id, title)


def test_title_is_requested_once_and_only_the_write_is_retried(tmp_path):
    written, requests = [], []
    with StorageRepository(tmp_path / "db.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        store = TitleFailingStore(sessions, [StorageError("busy"), KeyboardInterrupt()])
        recorder = SessionRecorder(store, "k7f2qa", write=written.append,
                                   titler=lambda q, a: requests.append(q) or "Titre unique")
        for turns in range(1, 5):
            recorder.after_turn(completed_session(*((f"Q{i}", f"A{i}") for i in range(turns))))
        assert requests == ["Q0"]
        assert store.titles == ["Titre unique"] * 3
        assert written == ["error: session title not saved: busy",
                           "error: session title not saved: interrupted"]
        assert [s.title for s in sessions.list()] == ["Titre unique"]


def test_ctrl_c_right_after_begin_does_not_lose_the_session(tmp_path):
    written = []
    with StorageRepository(tmp_path / "db.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        repository._connection = InterruptingConnection(repository._connection, "BEGIN IMMEDIATE")
        recorder = SessionRecorder(sessions, "k7f2qa", write=written.append)
        recorder.after_turn(completed_session(("Q1", "A1")))
        assert written == ["error: session not saved: interrupted"]
        assert sessions.list() == ()
        session = completed_session(("Q1", "A1"), ("Q2", "A2"))
        recorder.after_turn(session)
        assert written == ["error: session not saved: interrupted"]
        assert sessions.load("k7f2qa").messages == tuple(session.messages[1:])
        assert [s.title for s in sessions.list()] == ["Q1"]


def test_ctrl_c_during_a_save_is_reported_and_rolled_back(tmp_path, monkeypatch):
    written = []
    original = sqlite_store._now
    interrupt = []

    def now():  # called after the sessions upsert, inside the same transaction
        if interrupt:
            raise interrupt.pop()
        return original()

    with StorageRepository(tmp_path / "db.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        recorder = SessionRecorder(sessions, "k7f2qa", write=written.append)
        monkeypatch.setattr(sqlite_store, "_now", now)
        interrupt.append(KeyboardInterrupt())
        recorder.after_turn(completed_session(("Q1", "A1")))
        assert sessions.load("k7f2qa") is None and not recorder.saved
        recorder.after_turn(completed_session(("Q1", "A1"), ("Q2", "A2")))
        interrupt.append(KeyboardInterrupt())
        recorder.persona_changed("analyse")
        assert written == ["error: session not saved: interrupted"] * 2
        assert sessions.load("k7f2qa").persona_id is None
        recorder.after_turn(completed_session(("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")))
        snapshot = sessions.load("k7f2qa")
        assert (len(snapshot.messages), snapshot.persona_id, len(written)) == (6, "analyse", 2)
