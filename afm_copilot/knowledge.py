"""
The project's memory: what we have learned, kept with the application.

Everything worked out about these scans and about Gwyddion goes into
`knowledge/` as plain notes. Not documentation for a reader who already knows
the field -- findings, with what was measured and what it cost to find out.

Three properties make this the right shape:

  It lives with the app.   The notes are in the repository, versioned with the
                           code that acts on them. A finding and the function
                           it justifies move together.

  It is plain text.        The user can read, correct and add to it without
                           going through anyone. A knowledge base only they can
                           read through an interface is not theirs.

  Claude can consult it.   The MCP server exposes it, so an answer given in
                           conversation rests on what was actually measured
                           here rather than on general knowledge about AFM.

The intended failure mode is a note that turns out to be wrong. Each carries
the date and the evidence, so it can be checked and corrected rather than
quietly trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Words carrying no meaning for a search. Filtering by length alone would be
# wrong -- "RMS" and "tip" are three letters and are exactly what someone
# searches for. Both languages, because the user asks in either.
_STOPWORDS = {
    # English
    "the", "and", "for", "was", "are", "this", "that", "with", "from", "have",
    "has", "had", "not", "but", "what", "when", "how", "why", "does", "did",
    "can", "should", "would", "could", "there", "their", "then", "than",
    "been", "being", "were", "will", "any", "all", "one", "two", "its",
    "into", "onto", "out", "over", "under", "about", "which", "who", "whom",
    # Italian
    "che", "come", "sono", "questo", "questa", "quello", "quella", "con",
    "per", "una", "uno", "del", "della", "delle", "dei", "degli", "nel",
    "nella", "sul", "sulla", "gli", "non", "più", "meno", "molto", "poco",
    "cosa", "perche", "perché", "quando", "dove", "quale", "quali", "fare",
    "faccio", "posso", "devo", "essere", "avere", "stato", "sta", "ancora",
}


@dataclass
class Note:
    """One thing learned."""

    slug: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    verified: str = ""
    confidence: str = "measured"   # measured | observed | assumed
    path: Path | None = None

    @property
    def summary(self) -> str:
        """The first paragraph, which is where the finding itself belongs."""
        for block in self.body.split("\n\n"):
            text = block.strip()
            if text and not text.startswith("#"):
                return " ".join(text.split())
        return ""

    def matches(self, query: str) -> int:
        """
        How well this note answers a query. Zero means not at all.

        Scored word by word, because a real question is a phrase -- "polynomial
        background mask" must find the note about masked polynomial fits, and
        matching the whole phrase literally finds nothing.
        """
        words = [w for w in re.findall(r"\w+", query.lower())
                 if len(w) > 2 and w not in _STOPWORDS]
        if not words:
            return 0

        title = self.title.lower()
        body = self.body.lower()
        tags = " ".join(self.tags).lower()

        score = 0
        for word in words:
            if word in title:
                score += 10
            if word in tags:
                score += 6
            # Whole-word hits, so "mask" does not match "unmasked".
            score += 2 * len(re.findall(rf"\b{re.escape(word)}", body))
        return score


def _parse(path: Path) -> Note | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    meta: dict[str, str] = {}
    match = _FRONT.match(text)
    body = text
    if match:
        body = text[match.end():]
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip()

    tags = [t.strip() for t in meta.get("tags", "").strip("[]").split(",")
            if t.strip()]
    return Note(
        slug=path.stem,
        title=meta.get("title", path.stem.replace("-", " ")),
        body=body.strip(),
        tags=tags,
        verified=meta.get("verified", ""),
        confidence=meta.get("confidence", "measured"),
        path=path,
    )


def load_notes(directory: str | Path | None = None) -> list[Note]:
    """Every note, newest-verified first."""
    directory = Path(directory) if directory else KNOWLEDGE_DIR
    if not directory.is_dir():
        return []
    notes = [n for n in (_parse(p) for p in sorted(directory.glob("*.md"))) if n]
    return sorted(notes, key=lambda n: n.verified, reverse=True)


def recall(query: str = "", limit: int = 5,
           directory: str | Path | None = None) -> list[Note]:
    """
    The notes that bear on a question.

    With no query, returns the most recently verified — which is what someone
    picking the project up again wants to see.
    """
    notes = load_notes(directory)
    if not query.strip():
        return notes[:limit]
    scored = [(n.matches(query), n) for n in notes]
    return [n for score, n in sorted(scored, key=lambda s: -s[0]) if score > 0][:limit]


def add_note(
    slug: str,
    title: str,
    body: str,
    tags: list[str] | None = None,
    confidence: str = "measured",
    directory: str | Path | None = None,
) -> Path:
    """
    Write a new finding.

    Refuses to overwrite: a note that is wrong should be edited deliberately,
    with its history visible in git, not replaced by a later run.
    """
    directory = Path(directory) if directory else KNOWLEDGE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.md"
    if path.exists():
        raise FileExistsError(
            f"{path.name} already exists. Edit it rather than replacing it, so "
            f"the correction is visible in the history.")

    front = "\n".join([
        "---",
        f"title: {title}",
        f"tags: [{', '.join(tags or [])}]",
        f"verified: {date.today().isoformat()}",
        f"confidence: {confidence}",
        "---",
        "",
    ])
    path.write_text(front + body.strip() + "\n", encoding="utf-8")
    return path


def index() -> str:
    """A readable list of everything known, for a person or for Claude."""
    notes = load_notes()
    if not notes:
        return "Nothing recorded yet."
    lines = [f"{len(notes)} note(s) in {KNOWLEDGE_DIR}:", ""]
    for n in notes:
        tags = f"  [{', '.join(n.tags)}]" if n.tags else ""
        lines.append(f"  {n.slug}{tags}")
        lines.append(f"      {n.title}")
        lines.append(f"      {n.summary[:150]}")
        lines.append("")
    return "\n".join(lines)
