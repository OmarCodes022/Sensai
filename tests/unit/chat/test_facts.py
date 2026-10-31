"""The fact sheet (M3): queued tool changes, applied only when a turn completes."""
from datetime import date

from sensai.chat.facts import FACTS_HEADER, FactMemory, with_facts
from sensai.memory.sqlite_store import StorageRepository


def memory(tmp_path, creator="default"):
    repository = StorageRepository(tmp_path / "s.db")
    return repository, FactMemory(repository.for_creator(creator).facts, today=lambda: date(2026, 10, 31))


def test_save_is_queued_then_written_on_commit_with_its_source(tmp_path):
    repository, facts = memory(tmp_path)
    result = facts.save({"id": "hydra-glow-serum.price", "text": "Costs  29 €"})
    assert result.error is None and result.output.startswith("Will add hydra-glow-serum.price")
    assert facts.facts() == ()
    assert facts.commit() == ["Memory: added hydra-glow-serum.price"]
    assert [(f.id, f.text, f.source) for f in facts.facts()] == [("hydra-glow-serum.price", "Costs 29 €", "chat 2026-10-31")]
    repository.close()


def test_a_correction_updates_and_a_delete_removes(tmp_path):
    repository, facts = memory(tmp_path)
    facts.save({"id": "hydra-glow-serum.price", "text": "Costs 29 €"})
    facts.commit()
    assert facts.save({"id": "hydra-glow-serum.price", "text": "Costs 32 €"}).output.startswith("Will update")
    assert facts.commit() == ["Memory: updated hydra-glow-serum.price"]
    assert [f.text for f in facts.facts()] == ["Costs 32 €"]
    assert facts.delete({"id": "hydra-glow-serum.price"}).error is None
    assert facts.commit() == ["Memory: deleted hydra-glow-serum.price"] and facts.facts() == ()
    repository.close()


def test_bad_arguments_and_unknown_deletes_are_errors_that_change_nothing(tmp_path):
    repository, facts = memory(tmp_path)
    for arguments in ({"id": "Price", "text": "x"}, {"id": "price", "text": "x"}, {"id": "a.b", "text": " "},
                      {"id": "a.b", "text": "two\nlines"}, {"id": "a.b", "text": "x" * 301}, {"id": 3, "text": "x"}):
        assert facts.save(arguments).error
    assert facts.delete({"id": "nope.price"}).error
    assert facts.commit() == [] and facts.facts() == ()
    repository.close()


def test_dropped_changes_are_never_written(tmp_path):
    repository, facts = memory(tmp_path)
    facts.save({"id": "brand.name", "text": "Serein Studio"})
    facts.drop()
    assert facts.commit() == [] and facts.facts() == ()
    repository.close()


def test_facts_stay_separate_per_creator(tmp_path):
    repository, nadia = memory(tmp_path)
    other = FactMemory(repository.for_creator("other").facts)
    nadia.save({"id": "brand.name", "text": "Serein Studio"})
    nadia.commit()
    assert other.facts() == () and other.block() == ""
    repository.close()


def test_the_block_is_replaced_in_place_before_documents_and_tools(tmp_path):
    repository, facts = memory(tmp_path)
    facts.save({"id": "brand.name", "text": "Serein Studio"})
    facts.commit()
    prompt = with_facts("Rules\n\nDOCS\n\nTOOLS", facts.block(), "TOOLS", "DOCS")
    assert prompt == f"Rules\n\n{FACTS_HEADER}\n- brand.name: Serein Studio\n\nDOCS\n\nTOOLS"
    facts.delete({"id": "brand.name"})
    facts.commit()
    assert with_facts(prompt, facts.block(), "TOOLS", "DOCS") == "Rules\n\nDOCS\n\nTOOLS"
    repository.close()
