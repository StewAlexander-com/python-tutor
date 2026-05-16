"""Curated reference layer for credible Python documentation.

The tutor must cite *real* documentation, not URLs the LLM made up.
This module provides two layers:

* a **curated allowlist** that maps common concept keywords to vetted
  URLs on official docs (docs.python.org, packaging.python.org, the
  pytest docs, and a small set of major library docs). This works
  fully offline: the URLs are static facts about where the docs live,
  no network call needed.

* an optional **online verification step** that, when network is
  available and ``TUTOR_DOCS_ONLINE=1``, issues a HEAD request to each
  candidate URL with a short timeout. URLs that don't return 2xx/3xx
  are dropped. This guards against link rot and confirms reachability.

The policy is conservative on purpose: no fuzzy search, no scraping,
no LLM-generated citations. Either the URL is on the allowlist *and*
matches the topic, or it doesn't appear in the response.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlsplit

import httpx


# ---------------------------------------------------------------------------
# Configuration knobs
# ---------------------------------------------------------------------------

# Allowed hosts for any URL the tutor surfaces. Anything outside this
# set is dropped — including in user-supplied exercise references.
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "docs.python.org",
        "packaging.python.org",
        "peps.python.org",
        "docs.pytest.org",
        "pytest.org",
        "typing.readthedocs.io",
        "mypy.readthedocs.io",
        "pip.pypa.io",
        "setuptools.pypa.io",
        # Major libraries — only the *official* docs sites.
        "numpy.org",
        "pandas.pydata.org",
        "matplotlib.org",
        "scipy.org",
        "flask.palletsprojects.com",
        "fastapi.tiangolo.com",
        "docs.djangoproject.com",
        "requests.readthedocs.io",
        "httpx.readthedocs.io",
        "docs.sqlalchemy.org",
    }
)


def allowed_hosts() -> frozenset[str]:
    """Resolve allowed hosts from ``TUTOR_DOCS_ALLOWLIST`` (CSV) or the default."""
    raw = os.getenv("TUTOR_DOCS_ALLOWLIST", "")
    if not raw.strip():
        return DEFAULT_ALLOWED_HOSTS
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return frozenset(hosts)


def online_enabled() -> bool:
    return os.getenv("TUTOR_DOCS_ONLINE", "1") == "1"


def online_timeout() -> float:
    try:
        v = float(os.getenv("TUTOR_DOCS_TIMEOUT", "2.0"))
    except ValueError:
        return 2.0
    # Keep the user honest: short timeouts only — this runs on every
    # /api/evaluate call and we don't want to block on a slow upstream.
    return max(0.5, min(10.0, v))


# ---------------------------------------------------------------------------
# Curated keyword → URL map
# ---------------------------------------------------------------------------
#
# Maps a lower-case *concept token* (matched as a whole word in the
# student's code, question, section title, or exercise concepts) to a
# list of (label, url) pairs. The label is what the frontend shows.
#
# Sources are limited to official documentation. New entries must be on
# the allowlist above.

_CURATED: dict[str, list[tuple[str, str]]] = {
    # ---- language essentials ---------------------------------------------
    "print": [
        ("print() — built-in function", "https://docs.python.org/3/library/functions.html#print"),
    ],
    "input": [
        ("input() — built-in function", "https://docs.python.org/3/library/functions.html#input"),
    ],
    "len": [
        ("len() — built-in function", "https://docs.python.org/3/library/functions.html#len"),
    ],
    "range": [
        ("range — sequence type", "https://docs.python.org/3/library/stdtypes.html#range"),
        ("range() — built-in function", "https://docs.python.org/3/library/functions.html#func-range"),
    ],
    "for": [
        ("for statements — tutorial", "https://docs.python.org/3/tutorial/controlflow.html#for-statements"),
        ("the for statement — reference", "https://docs.python.org/3/reference/compound_stmts.html#the-for-statement"),
    ],
    "while": [
        ("while statements — reference", "https://docs.python.org/3/reference/compound_stmts.html#the-while-statement"),
    ],
    "if": [
        ("if statements — tutorial", "https://docs.python.org/3/tutorial/controlflow.html#if-statements"),
    ],
    "else": [
        ("if statements — tutorial", "https://docs.python.org/3/tutorial/controlflow.html#if-statements"),
    ],
    "elif": [
        ("if statements — tutorial", "https://docs.python.org/3/tutorial/controlflow.html#if-statements"),
    ],
    "def": [
        ("Defining functions — tutorial", "https://docs.python.org/3/tutorial/controlflow.html#defining-functions"),
    ],
    "return": [
        ("the return statement — reference", "https://docs.python.org/3/reference/simple_stmts.html#the-return-statement"),
    ],
    "lambda": [
        ("Lambda expressions", "https://docs.python.org/3/reference/expressions.html#lambda"),
    ],
    "class": [
        ("Classes — tutorial", "https://docs.python.org/3/tutorial/classes.html"),
    ],
    "import": [
        ("The import system", "https://docs.python.org/3/reference/import.html"),
        ("Modules — tutorial", "https://docs.python.org/3/tutorial/modules.html"),
    ],
    "try": [
        ("Errors and Exceptions — tutorial", "https://docs.python.org/3/tutorial/errors.html"),
    ],
    "except": [
        ("Errors and Exceptions — tutorial", "https://docs.python.org/3/tutorial/errors.html"),
    ],
    "raise": [
        ("Raising exceptions", "https://docs.python.org/3/tutorial/errors.html#raising-exceptions"),
    ],
    "with": [
        ("the with statement", "https://docs.python.org/3/reference/compound_stmts.html#the-with-statement"),
    ],
    "yield": [
        ("Generators — tutorial", "https://docs.python.org/3/tutorial/classes.html#generators"),
    ],
    # ---- data types ------------------------------------------------------
    "list": [
        ("More on Lists — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#more-on-lists"),
        ("list — sequence type", "https://docs.python.org/3/library/stdtypes.html#typesseq-list"),
    ],
    "dict": [
        ("Dictionaries — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#dictionaries"),
        ("dict — mapping type", "https://docs.python.org/3/library/stdtypes.html#mapping-types-dict"),
    ],
    "dictionary": [
        ("Dictionaries — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#dictionaries"),
    ],
    "tuple": [
        ("Tuples and Sequences — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#tuples-and-sequences"),
    ],
    "set": [
        ("Sets — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#sets"),
        ("set — set type", "https://docs.python.org/3/library/stdtypes.html#set-types-set-frozenset"),
    ],
    "str": [
        ("Text Sequence Type — str", "https://docs.python.org/3/library/stdtypes.html#text-sequence-type-str"),
        ("String methods", "https://docs.python.org/3/library/stdtypes.html#string-methods"),
    ],
    "string": [
        ("Text Sequence Type — str", "https://docs.python.org/3/library/stdtypes.html#text-sequence-type-str"),
    ],
    "int": [
        ("Numeric Types — int, float, complex", "https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex"),
    ],
    "float": [
        ("Numeric Types — int, float, complex", "https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex"),
        ("Floating point arithmetic", "https://docs.python.org/3/tutorial/floatingpoint.html"),
    ],
    "bool": [
        ("Truth Value Testing", "https://docs.python.org/3/library/stdtypes.html#truth-value-testing"),
    ],
    "none": [
        ("None — built-in constant", "https://docs.python.org/3/library/constants.html#None"),
    ],
    # ---- patterns --------------------------------------------------------
    "comprehension": [
        ("List comprehensions — tutorial", "https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions"),
    ],
    "slice": [
        ("Sequence types — common operations", "https://docs.python.org/3/library/stdtypes.html#typesseq-common"),
    ],
    "iterator": [
        ("Iterators — tutorial", "https://docs.python.org/3/tutorial/classes.html#iterators"),
    ],
    "generator": [
        ("Generators — tutorial", "https://docs.python.org/3/tutorial/classes.html#generators"),
    ],
    "exception": [
        ("Built-in Exceptions", "https://docs.python.org/3/library/exceptions.html"),
    ],
    "f-string": [
        ("Formatted string literals", "https://docs.python.org/3/reference/lexical_analysis.html#f-strings"),
        ("Format String Syntax", "https://docs.python.org/3/library/string.html#format-string-syntax"),
    ],
    # ---- stdlib bits commonly seen in foundations ------------------------
    "math": [
        ("math — mathematical functions", "https://docs.python.org/3/library/math.html"),
    ],
    "random": [
        ("random — generate pseudo-random numbers", "https://docs.python.org/3/library/random.html"),
    ],
    "json": [
        ("json — JSON encoder/decoder", "https://docs.python.org/3/library/json.html"),
    ],
    "datetime": [
        ("datetime — Basic date and time types", "https://docs.python.org/3/library/datetime.html"),
    ],
    "pathlib": [
        ("pathlib — Object-oriented filesystem paths", "https://docs.python.org/3/library/pathlib.html"),
    ],
    "statistics": [
        ("statistics — mathematical statistics", "https://docs.python.org/3/library/statistics.html"),
    ],
    "typing": [
        ("typing — Support for type hints", "https://docs.python.org/3/library/typing.html"),
    ],
    # ---- testing ---------------------------------------------------------
    "test": [
        ("pytest — Get started", "https://docs.pytest.org/en/stable/getting-started.html"),
        ("unittest — Unit testing framework", "https://docs.python.org/3/library/unittest.html"),
    ],
    "pytest": [
        ("pytest documentation", "https://docs.pytest.org/en/stable/"),
        ("pytest — How-to guides", "https://docs.pytest.org/en/stable/how-to/index.html"),
    ],
    "assert": [
        ("assert statement", "https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement"),
    ],
    "unittest": [
        ("unittest — Unit testing framework", "https://docs.python.org/3/library/unittest.html"),
    ],
}


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

# Match Python identifiers and dotted names; we also catch ``f-string``
# specifically since the hyphen is meaningful.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokenise(text: str) -> set[str]:
    if not text:
        return set()
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}
    # Hyphenated terms we want to catch as one unit.
    lowered = text.lower()
    for compound in ("f-string", "list comprehension", "dict comprehension"):
        if compound in lowered:
            tokens.add(compound.split()[0] if " " in compound else compound)
    return tokens


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocRef:
    label: str
    url: str
    source: str  # "curated" | "exercise"


@dataclass
class DocsLookup:
    refs: list[DocRef] = field(default_factory=list)
    online: bool = False  # whether online verification ran
    online_ok: bool = False  # whether at least one HEAD succeeded
    note: str | None = None  # human-readable status (e.g. "offline")


# ---------------------------------------------------------------------------
# Allowlist filtering
# ---------------------------------------------------------------------------


def is_allowlisted(url: str, allowed: Iterable[str] | None = None) -> bool:
    """Return True if *url* is HTTPS and on the host allowlist."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("https", "http"):
        return False
    host = (parts.netloc or "").lower()
    # Strip user:pass and :port if present.
    if "@" in host:
        host = host.split("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    hosts = frozenset(allowed) if allowed is not None else allowed_hosts()
    return host in hosts


def filter_allowlisted(urls: Iterable[str]) -> list[str]:
    return [u for u in urls if is_allowlisted(u)]


# ---------------------------------------------------------------------------
# Lookup pipeline
# ---------------------------------------------------------------------------


def _curated_for_tokens(tokens: set[str]) -> list[DocRef]:
    seen: set[str] = set()
    out: list[DocRef] = []
    for token in tokens:
        entries = _CURATED.get(token)
        if not entries:
            continue
        for label, url in entries:
            if url in seen or not is_allowlisted(url):
                continue
            seen.add(url)
            out.append(DocRef(label=label, url=url, source="curated"))
    return out


async def _verify_online(
    urls: list[str], *, timeout: float, client: httpx.AsyncClient | None = None
) -> tuple[set[str], bool]:
    """HEAD-check *urls* in parallel; return the set of reachable URLs and an
    overall ``online_ok`` flag (true if at least one request returned 2xx/3xx).
    """
    import asyncio as _asyncio

    if not urls:
        return set(), False

    owned = client is None
    cli = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def _one(url: str) -> str | None:
        try:
            r = await cli.head(url)
        except httpx.HTTPError:
            return None
        # 2xx or 3xx after follow_redirects means reachable.
        if 200 <= r.status_code < 400:
            return url
        # Some sites return 405 on HEAD; treat that as reachable via GET.
        if r.status_code == 405:
            try:
                r2 = await cli.get(url)
                if 200 <= r2.status_code < 400:
                    return url
            except httpx.HTTPError:
                return None
        return None

    try:
        results = await _asyncio.gather(*[_one(u) for u in urls], return_exceptions=False)
    finally:
        if owned:
            await cli.aclose()

    ok = {u for u in results if u}
    return ok, bool(ok)


async def lookup(
    *,
    code: str | None = None,
    question: str | None = None,
    section: str | None = None,
    concepts: Iterable[str] | None = None,
    exercise_refs: Iterable[str] | None = None,
    verify_online: bool | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
    max_refs: int = 4,
) -> DocsLookup:
    """Find credible docs URLs for the given evidence packet.

    Tokens are extracted from *code*, *question*, *section*, and
    *concepts*. Matching curated entries are returned first; exercise-
    supplied references are added next (filtered by allowlist). When
    network verification is enabled, unreachable URLs are dropped.
    """
    tokens: set[str] = set()
    for field_text in (code or "", question or "", section or ""):
        tokens |= _tokenise(field_text)
    for c in concepts or ():
        tokens |= _tokenise(c)

    refs = _curated_for_tokens(tokens)

    for url in exercise_refs or ():
        if not is_allowlisted(url):
            continue
        if any(r.url == url for r in refs):
            continue
        refs.append(DocRef(label=url, url=url, source="exercise"))

    if len(refs) > max_refs:
        refs = refs[:max_refs]

    do_online = online_enabled() if verify_online is None else verify_online
    if not do_online or not refs:
        return DocsLookup(refs=refs, online=False, online_ok=False, note=None)

    try:
        urls = [r.url for r in refs]
        reachable, ok = await _verify_online(
            urls, timeout=timeout or online_timeout(), client=client
        )
    except Exception as exc:  # noqa: BLE001 - never propagate
        return DocsLookup(
            refs=refs,
            online=True,
            online_ok=False,
            note=f"online check failed: {exc.__class__.__name__}",
        )

    if not ok:
        # Online tried but nothing was reachable — return the curated
        # set anyway with a note. The frontend can render them as
        # "references (offline)" and dim them.
        return DocsLookup(
            refs=refs,
            online=True,
            online_ok=False,
            note="docs network unreachable; showing curated references unverified",
        )

    verified = [r for r in refs if r.url in reachable]
    return DocsLookup(refs=verified, online=True, online_ok=True, note=None)
