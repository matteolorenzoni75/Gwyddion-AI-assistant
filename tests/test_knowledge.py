"""
Tests for the project's memory.

The store's job is to answer a question asked in ordinary words. The failure
that matters is a note that exists but is not found, because the effect is
indistinguishable from not knowing — and the answer given instead comes from
general knowledge rather than from what was measured here.
"""

from __future__ import annotations

import pytest

from afm_copilot.knowledge import (KNOWLEDGE_DIR, add_note, index, load_notes,
                                   recall)


@pytest.fixture
def store(tmp_path):
    """A small knowledge folder with two notes that could be confused."""
    add_note("masked-fit", "A masked polynomial fit leaves objects intact",
             "Fitting the background around a mask left a flat object flat to "
             "0.3 nm, against 8.4 nm when fitted through it.\n\n"
             "The degree still has to be chosen from the data.",
             tags=["masking", "polynomial", "background"], directory=tmp_path)
    add_note("already-levelled", "Some scans arrive already levelled",
             "Measured tilt was exactly 0% on the two scans the instrument had "
             "levelled, and 26-81% on the rest.",
             tags=["provenance", "tilt"], directory=tmp_path)
    return tmp_path


def test_notes_are_read_with_their_metadata(store):
    notes = load_notes(store)
    assert len(notes) == 2
    masked = next(n for n in notes if n.slug == "masked-fit")
    assert masked.title.startswith("A masked polynomial fit")
    assert "masking" in masked.tags
    assert masked.verified          # dated on writing
    assert masked.confidence == "measured"


def test_summary_is_the_finding_not_the_heading(store):
    note = next(n for n in load_notes(store) if n.slug == "masked-fit")
    assert note.summary.startswith("Fitting the background around a mask")


def test_a_question_in_ordinary_words_finds_the_right_note(store):
    """The case that matters: a phrase, not a keyword."""
    hits = recall("polynomial background with a mask", directory=store)
    assert hits
    assert hits[0].slug == "masked-fit"


def test_a_different_question_finds_the_other_note(store):
    hits = recall("was this scan already processed by the instrument",
                  directory=store)
    assert hits
    assert hits[0].slug == "already-levelled"


def test_short_words_do_not_match_everything(store):
    """'is', 'a', 'the' must not drag in every note."""
    assert recall("is a the of", directory=store) == []


def test_whole_words_only(store):
    """'mask' should not be found by searching for an unrelated longer word."""
    assert recall("unmaskable", directory=store) == []


def test_empty_query_returns_what_is_known(store):
    assert len(recall("", directory=store)) == 2


def test_a_note_is_not_silently_replaced(store):
    """A wrong note should be corrected deliberately, with a visible history."""
    with pytest.raises(FileExistsError, match="already exists"):
        add_note("masked-fit", "Something else", "body", directory=store)


def test_index_lists_everything(store):
    from afm_copilot import knowledge
    text = index() if KNOWLEDGE_DIR.is_dir() else ""
    # The real project folder should already carry findings.
    if text and text != "Nothing recorded yet.":
        assert "note(s) in" in text


def test_the_real_knowledge_folder_is_readable():
    """Whatever is committed must parse -- a broken note is silently lost."""
    for note in load_notes():
        assert note.title, f"{note.slug} has no title"
        assert note.summary, f"{note.slug} has no finding in its first paragraph"
        assert note.verified, f"{note.slug} is undated"
