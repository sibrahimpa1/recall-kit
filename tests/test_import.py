"""Importing existing notes: sources kept, duplicates merged, injections quarantined."""

from __future__ import annotations

from pathlib import Path

from recall_kit.importer import collect, guess_type, import_items, parse_text
from recall_kit.store import MemoryStore

from .conftest import cli_json

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_memory_list_import_dry_run_then_real(home: Path) -> None:
    path = EXAMPLES / "chatgpt-saved-memories.txt"
    dry = cli_json(home, "import", str(path), "--origin", "ChatGPT saved memories", "--dry-run")
    assert dry["counts"] == {"would_import": 7, "would_quarantine": 1}
    assert cli_json(home, "list") == []  # a dry run writes nothing

    real = cli_json(home, "import", str(path), "--origin", "ChatGPT saved memories")
    assert real["counts"] == {"created": 7, "quarantined": 1}
    store = MemoryStore(home)
    hit = store.recall("when does the bakery open")["results"][0]
    assert "06:30" in hit["content"]
    assert hit["source"]["origin"] == "ChatGPT saved memories: chatgpt-saved-memories.txt › Saved memories"
    assert "imported" in hit["tags"]
    assert not any(
        "system prompt" in r["content"] for r in store.recall("reveal the system prompt", k=10)["results"]
    )

    again = cli_json(home, "import", str(path), "--origin", "ChatGPT saved memories")
    assert again["counts"] == {"duplicate": 8}  # importing twice changes nothing


def test_notes_folder_import_keeps_file_and_heading_as_source(home: Path) -> None:
    items = collect(EXAMPLES / "notion-export", "Notion export")
    sources = {i.source for i in items}
    assert "Notion export: Clients/Juniper & Rye Bakery › Contacts" in sources  # Notion's id suffix stripped
    assert "Notion export: Operating notes › Tools" in sources
    assert not any(
        "code blocks are skipped" in i.content or "Opening" in i.content or "tags: ops" in i.content
        for i in items
    )  # code, tables and frontmatter are not memories
    res = import_items(MemoryStore(home), items, project=None)
    assert res["counts"] == {"created": 7}


def test_type_guessing_and_parsing() -> None:
    assert guess_type("Prefers phone calls before 10:00") == "preference"
    assert guess_type("We decided to use Postgres") == "decision"
    assert guess_type("The office is on Canal Road") == "fact"
    items = parse_text(
        "# Title\n\nshort\n\n1. First numbered memory item.\n- [x] A checked task that is long enough.\n",
        "src",
    )
    assert [i.content for i in items] == [
        "First numbered memory item.",
        "A checked task that is long enough.",
    ]
    assert items[0].source == "src › Title"
