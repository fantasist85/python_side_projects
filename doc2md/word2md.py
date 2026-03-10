#!/usr/bin/env python3
"""
docx_to_markdown_v2.py
=======================
LLM-optimised DOCX → Markdown converter for automotive requirement documents.
(TSR / FSR / SRS / HWR / SWR and similar Korean-English mixed specs)

Design goals vs. naive converters
──────────────────────────────────
1. Direct python-docx parsing (no pandoc dependency for core logic)
   → Preserves paragraph structure *inside* table cells faithfully
   → No pandoc grid-table / HTML-table artefacts to clean up

2. TSR / FSR entry tables rendered as structured YAML-like blocks
   (not pipe tables) so LLMs can extract fields by name reliably

3. Multi-paragraph cell values kept as numbered/bulleted sub-lists,
   not collapsed into one long line

4. Heading hierarchy (H1–H5) mapped cleanly to #–##### Markdown

5. YAML front-matter + auto-generated section index added at the top
   → Lets LLMs orient themselves before reading the full document

6. List paragraphs (Word "List Paragraph" style) emitted as - bullets

7. Graceful fallback: unknown styles treated as Normal paragraphs

Usage
─────
    # single file
    python docx_to_markdown_v2.py input.docx

    # custom output
    python docx_to_markdown_v2.py input.docx -o output.md

    # batch (all .docx in a directory)
    python docx_to_markdown_v2.py ./specs/ --batch [--output-dir ./md/]

    # options
    --no-frontmatter    skip YAML header
    --no-index          skip section index block
    --no-tsr-blocks     render TSR/FSR tables as pipe tables instead

Requirements
────────────
    pip install python-docx --break-system-packages
    (lxml is optional – used only for fallback HTML table parsing if present)
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import textwrap
from pathlib import Path
from typing import Callable

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table, _Row

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

HEADING_MAP: dict[str, str] = {
    "Heading 1": "#",
    "Heading 2": "##",
    "Heading 3": "###",
    "Heading 4": "####",
    "Heading 5": "#####",
    "Title":     "#",
}

# Attribute keys that mark a TSR entry table
TSR_KEYS: frozenset[str] = frozenset({
    "id", "state", "requirement", "asil", "fhti", "allocation",
    "related id", "verification method", "verification criteria",
    "release priority", "status",
})

# Attribute keys that mark an FSR entry table
FSR_KEYS: frozenset[str] = frozenset({
    "fsr", "safety goal", "input", "output", "asil",
})

# Attribute keys whose values should be rendered as indented sub-lists
# when they contain multiple paragraphs
MULTILINE_KEYS: frozenset[str] = frozenset({
    "requirement", "fsr", "safety goal",
    "verification criteria", "description",
})

# Keys that are typically single-line – collapse their paragraphs
SINGLELINE_KEYS: frozenset[str] = frozenset({
    "id", "asil", "fhti", "allocation", "related id",
    "verification method", "release priority", "status",
    "input", "output", "state",
})


# ──────────────────────────────────────────────────────────────────────────────
# Cell text extraction  (preserves multi-paragraph structure)
# ──────────────────────────────────────────────────────────────────────────────

def _cell_paragraphs(cell) -> list[str]:
    """Return non-empty paragraph texts from a table cell."""
    return [p.text.strip() for p in cell.paragraphs if p.text.strip()]


def _cell_text_flat(cell) -> str:
    """Single-line cell text (newlines → space)."""
    return " ".join(_cell_paragraphs(cell))


# ──────────────────────────────────────────────────────────────────────────────
# Table type detection
# ──────────────────────────────────────────────────────────────────────────────

def _first_col_keys(table: Table) -> frozenset[str]:
    return frozenset(
        row.cells[0].text.strip().lower()
        for row in table.rows
        if row.cells
    )


def _classify_table(table: Table) -> str:
    """
    Returns one of: 'tsr' | 'fsr' | 'generic'
    """
    keys = _first_col_keys(table)
    if len(keys & TSR_KEYS) >= 3:
        return "tsr"
    if len(keys & FSR_KEYS) >= 2:
        return "fsr"
    return "generic"


# ──────────────────────────────────────────────────────────────────────────────
# Table renderers
# ──────────────────────────────────────────────────────────────────────────────

def _render_attr_block(table: Table) -> str:
    """
    Render a 2-column TSR/FSR attribute table as a structured block.

    Format:
        **ID**: TSR_001
        **ASIL**: B(D)
        **Requirement**:
          - 시스템은 배터리 팩의 SoC를 측정할 수 있도록 회로 설계해야 한다
          - 다음의 조건들을 충족해야 한다.
          - 1. 배터리 셀 및 팩 전압 측정 회로 구성
        **Status**: Accepted
    """
    lines: list[str] = []
    for row in table.rows:
        if len(row.cells) < 2:
            continue
        key_raw = row.cells[0].text.strip()
        key_lower = key_raw.lower()

        # Skip the header row (Attribute / Description)
        if key_lower in ("attribute", "description", ""):
            continue

        val_paras = _cell_paragraphs(row.cells[1])
        if not val_paras:
            val_paras = ["*(empty)*"]

        # Multi-line rendering for content-heavy fields
        if key_lower in MULTILINE_KEYS and len(val_paras) > 1:
            lines.append(f"**{key_raw}**:")
            for vp in val_paras:
                lines.append(f"  - {vp}")
        else:
            # Single-line: collapse paragraphs
            val_flat = " ".join(val_paras)
            lines.append(f"**{key_raw}**: {val_flat}")

        lines.append("")   # blank line between attributes for readability

    return "\n".join(lines)


def _dedup_merged_cells(rows: list[_Row]) -> list[list[str]]:
    """
    Word merges cells by repeating the same cell object for spanned columns.
    De-duplicate horizontally so merged cells don't produce duplicate text.
    """
    result: list[list[str]] = []
    for row in rows:
        seen_ids: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            cid = id(cell._tc)
            if cid not in seen_ids:
                seen_ids.add(cid)
                cells.append(_cell_text_flat(cell))
        result.append(cells)
    return result


def _render_pipe_table(table: Table) -> str:
    """
    Render a generic table as a GFM pipe table.
    Handles horizontally merged cells (de-duplicates repeated cell objects).
    """
    rows = _dedup_merged_cells(table.rows)
    # Remove fully-empty rows
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""

    # Normalise column count
    n_cols = max(len(r) for r in rows)
    norm: list[list[str]] = []
    for r in rows:
        flat = [c.replace("|", "\\|") for c in r]
        while len(flat) < n_cols:
            flat.append("")
        norm.append(flat[:n_cols])

    widths = [max(max(len(r[i]) for r in norm), 3) for i in range(n_cols)]

    def _row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([_row(norm[0]), sep] + [_row(r) for r in norm[1:]])


def render_table(table: Table, force_pipe: bool = False) -> str:
    """Dispatch to the appropriate renderer."""
    if not force_pipe:
        ttype = _classify_table(table)
        if ttype in ("tsr", "fsr"):
            return _render_attr_block(table)
    return _render_pipe_table(table)


# ──────────────────────────────────────────────────────────────────────────────
# Paragraph renderer
# ──────────────────────────────────────────────────────────────────────────────

def _is_bold_paragraph(para) -> bool:
    """True if all non-whitespace runs in the paragraph are bold."""
    runs = [r for r in para.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def render_paragraph(para) -> str:
    """
    Convert a paragraph to Markdown.
    Handles: headings, list paragraphs, captions, normal text, bold-only lines.
    """
    style = para.style.name
    text = para.text.strip()

    if not text:
        return ""

    # Heading styles
    if style in HEADING_MAP:
        prefix = HEADING_MAP[style]
        return f"{prefix} {text}"

    # List Paragraph → bullet
    if style == "List Paragraph":
        return f"- {text}"

    # Caption → italic
    if style == "Caption":
        return f"*{text}*"

    # Bold-only paragraph (often used as sub-headings in Korean docs)
    if _is_bold_paragraph(para):
        return f"**{text}**"

    # Everything else (Normal, 예시, etc.)
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Front-matter & section index
# ──────────────────────────────────────────────────────────────────────────────

def _detect_doc_type(doc: Document) -> str:
    """Heuristic document type detection from first few paragraphs."""
    sample = " ".join(p.text for p in doc.paragraphs[:20]).upper()
    if "TECHNICAL SAFETY" in sample or "TSR" in sample:
        return "TSR"
    if "FUNCTIONAL SAFETY" in sample or "FSR" in sample:
        return "FSR"
    if "SYSTEM REQUIREMENT" in sample or "SRS" in sample:
        return "SRS"
    if "HARDWARE REQUIREMENT" in sample or "HWR" in sample:
        return "HWR"
    if "SOFTWARE REQUIREMENT" in sample or "SWR" in sample:
        return "SWR"
    return "Document"


def _detect_version(doc: Document) -> str:
    """Try to find latest version number from revision table."""
    # Look for a table whose first column has Version / 초안 / numbers
    for table in doc.tables[:3]:
        # Guard: skip tables with no rows (prevents IndexError)
        if not table.rows:
            continue
        header_texts = [c.text.strip().lower() for c in table.rows[0].cells]
        if "version" in header_texts or "date" in header_texts:
            # Walk rows in reverse – last row is latest version
            for row in reversed(table.rows[1:]):
                v = row.cells[0].text.strip()
                if re.match(r"[\d.]+", v):
                    return v
    return ""


def make_front_matter(doc: Document, source: Path) -> str:
    title = source.stem.replace("_", " ")
    # Try first non-empty, non-heading paragraph as title candidate
    for p in doc.paragraphs[:5]:
        if p.text.strip() and p.style.name not in HEADING_MAP:
            title = p.text.strip()
            break
    doc_type = _detect_doc_type(doc)
    version = _detect_version(doc)
    lines = [
        "---",
        f'title: "{title}"',
        f'document_type: "{doc_type}"',
    ]
    if version:
        lines.append(f'version: "{version}"')
    lines += [f'source: "{source.name}"', "---", ""]
    return "\n".join(lines)


def make_section_index(md_lines: list[str], limit: int = 120) -> str:
    headings: list[tuple[int, str]] = []
    for line in md_lines:
        m = re.match(r"^(#{1,5})\s+(.+)$", line)
        if m:
            headings.append((len(m.group(1)), m.group(2)))
    if not headings:
        return ""
    idx_lines = ["<!-- Section Index -->", ""]
    for level, text in headings[:limit]:
        idx_lines.append("  " * (level - 1) + f"- {text}")
    idx_lines += ["", "---", ""]
    return "\n".join(idx_lines)


# ──────────────────────────────────────────────────────────────────────────────
# Core document walker
# ──────────────────────────────────────────────────────────────────────────────

# Word XML tags
_TAG_P   = qn("w:p")
_TAG_TBL = qn("w:tbl")


def docx_to_md_lines(
    doc: Document,
    force_pipe: bool = False,
) -> list[str]:
    """
    Walk doc.element.body in document order, converting each element.
    Returns a list of Markdown lines (not yet joined).
    """
    table_index: dict = {t._element: t for t in doc.tables}
    para_index: dict  = {p._element: p for p in doc.paragraphs}

    output: list[str] = []
    prev_blank = True   # suppress leading blank lines

    def _emit(line: str) -> None:
        nonlocal prev_blank
        is_blank = not line.strip()
        if is_blank and prev_blank:
            return   # collapse consecutive blanks
        output.append(line)
        prev_blank = is_blank

    for child in doc.element.body:
        tag = child.tag

        if tag == _TAG_P:
            para = para_index.get(child)
            if para is None:
                continue
            md_line = render_paragraph(para)
            _emit(md_line)
            if md_line:
                _emit("")   # blank line after each content paragraph

        elif tag == _TAG_TBL:
            table = table_index.get(child)
            if table is None:
                continue
            rendered = render_table(table, force_pipe=force_pipe)
            if rendered:
                _emit("")
                for tline in rendered.splitlines():
                    _emit(tline)
                _emit("")

    return output


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline entry point
# ──────────────────────────────────────────────────────────────────────────────

def convert(
    input_path: Path,
    output_path: Path | None = None,
    add_frontmatter: bool = True,
    add_index: bool = True,
    force_pipe: bool = False,
) -> Path:
    if output_path is None:
        output_path = input_path.with_suffix(".md")

    logger.info("[convert] %s  →  %s", input_path.name, output_path.name)

    logger.info("  [1/3] Parsing DOCX …")
    doc = Document(str(input_path))

    logger.info("  [2/3] Converting …")
    md_lines = docx_to_md_lines(doc, force_pipe=force_pipe)

    logger.info("  [3/3] Assembling …")
    header_parts: list[str] = []

    if add_frontmatter:
        header_parts.append(make_front_matter(doc, input_path))

    md_body = "\n".join(md_lines)

    if add_index:
        idx = make_section_index(md_lines)
        if idx:
            header_parts.append(idx)

    full_md = "".join(header_parts) + md_body

    # Final pass: collapse 3+ blank lines → 2
    full_md = re.sub(r"\n{4,}", "\n\n\n", full_md)

    output_path.write_text(full_md, encoding="utf-8")
    size_kb = output_path.stat().st_size / 1024
    logger.info("  ✓ %.1f KB  →  %s", size_kb, output_path)
    return output_path


# ──────────────────────────────────────────────────────────────────────────────
# Batch mode
# ──────────────────────────────────────────────────────────────────────────────

def batch_convert(
    directory: Path,
    output_dir: Path | None = None,
    **kwargs,
) -> None:
    """Convert all .docx files found recursively under *directory*.

    Office lock files (~$*.docx) are automatically excluded.
    """
    files = sorted(
        f for f in directory.glob("**/*.docx")
        if not f.name.startswith("~$")
    )
    if not files:
        logger.info("No .docx files found in: %s", directory)
        return
    logger.info("Found %d file(s).", len(files))
    failed: list[tuple[Path, str]] = []
    for f in files:
        out = (output_dir / f.with_suffix(".md").name) if output_dir else f.with_suffix(".md")
        try:
            convert(f, out, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.error("  ✗ %s: %s", f.name, exc)
            failed.append((f, str(exc)))
    ok = len(files) - len(failed)
    logger.info("\nDone: %d/%d succeeded.", ok, len(files))
    for p, msg in failed:
        logger.error("  FAILED %s: %s", p.name, msg)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        prog="word2md",
        description=textwrap.dedent("""\
            ╔══════════════════════════════════════════════════════════════╗
            ║            word2md — DOCX → Markdown Converter              ║
            ║   LLM-optimised output for automotive requirement docs      ║
            ╚══════════════════════════════════════════════════════════════╝

            Converts Word (.docx) files to LLM-optimised Markdown.
            Designed for FuSa requirement documents:
            TSR / FSR / SRS / HWR / SWR and Korean-English mixed specs.

            Key features
            ────────────
              • Direct python-docx parsing — no pandoc dependency
                → Preserves paragraph structure inside table cells faithfully
              • TSR / FSR entry tables auto-detected and rendered as structured
                attribute blocks (bold key: value pairs), NOT pipe tables
                → LLMs can extract fields by name reliably
              • Generic tables rendered as GFM pipe tables
              • Multi-paragraph cell values kept as numbered/bulleted sub-lists
              • Heading hierarchy (H1–H5) mapped to #–##### Markdown
              • YAML front-matter + auto-generated section index at the top
              • List Paragraph style → bullet points
              • Graceful fallback: unknown styles treated as Normal paragraphs

            TSR / FSR table detection
            ─────────────────────────
              A table is classified as TSR if its first-column keys contain
              ≥ 3 of: id, state, requirement, asil, fhti, allocation,
              related id, verification method, verification criteria,
              release priority, status

              A table is classified as FSR if its first-column keys contain
              ≥ 2 of: fsr, safety goal, input, output, asil

              All other tables → generic pipe table.
              Use --pipe-tables to force pipe rendering for ALL tables.
        """),
        epilog=textwrap.dedent("""\
            Output path rules
            ─────────────────
              Single-file mode  →  output defaults to <input>.md in the same folder
                                   Override with -o / --output
              Batch mode        →  each file gets its own .md next to the source
                                   Override destination root with --output-dir

            YAML front-matter fields
            ────────────────────────
              title         : document title (heuristic from first paragraph)
              document_type : TSR / FSR / SRS / HWR / SWR / Document
              version       : latest version string from revision table (if found)
              source        : original filename

            Section index
            ─────────────
              Auto-generated from all Markdown headings in the converted body.
              Placed just after front-matter for quick LLM orientation.
              Capped at 120 entries.  Skip with --no-index.

            Examples
            ────────
              # Convert a single file (output: input.md)
              python word2md.py TSR_v1.2.docx

              # Specify output path
              python word2md.py TSR_v1.2.docx -o docs/TSR_v1.2.md

              # Force all tables as pipe tables (disable TSR/FSR block rendering)
              python word2md.py FSR.docx --pipe-tables

              # Batch-convert all .docx under ./specs/, outputs beside sources
              python word2md.py ./specs/ --batch

              # Batch with separate output directory
              python word2md.py ./specs/ --batch --output-dir ./md/

              # Minimal output (no front-matter, no index)
              python word2md.py input.docx --no-frontmatter --no-index
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help=(
            "Path to a .docx file (single-file mode), or a directory "
            "(--batch mode).  Office lock files (~$*.docx) are always skipped."
        ),
    )
    p.add_argument(
        "-o", "--output",
        metavar="PATH",
        help=(
            "Output .md file path.  Single-file mode only.  "
            "Defaults to <INPUT>.md in the same directory."
        ),
    )
    p.add_argument(
        "--batch", action="store_true",
        help=(
            "Convert ALL .docx files found recursively under INPUT.  "
            "Each output .md is placed next to its source file unless "
            "--output-dir is specified."
        ),
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        help=(
            "Destination directory for --batch mode.  "
            "All .md files are placed flat in this directory "
            "(sub-directory structure is NOT mirrored).  "
            "Directory is created if it does not exist."
        ),
    )
    p.add_argument(
        "--no-frontmatter", action="store_true",
        help=(
            "Omit the YAML front-matter block at the top of the output.  "
            "Useful when the .md will be embedded in a larger document."
        ),
    )
    p.add_argument(
        "--no-index", action="store_true",
        help=(
            "Omit the auto-generated section index block.  "
            "The index is derived from all headings in the converted document."
        ),
    )
    p.add_argument(
        "--pipe-tables", action="store_true",
        help=(
            "Render ALL tables as GFM pipe tables.  "
            "Disables automatic TSR/FSR attribute-block rendering.  "
            "Useful for non-FuSa documents or when pipe format is preferred."
        ),
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG-level) logging output.",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    inp = Path(args.input)
    kwargs: dict = dict(
        add_frontmatter=not args.no_frontmatter,
        add_index=not args.no_index,
        force_pipe=args.pipe_tables,
    )

    if args.batch:
        if not inp.is_dir():
            sys.exit("--batch requires a directory as input")
        out_dir = Path(args.output_dir) if args.output_dir else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
        batch_convert(inp, out_dir, **kwargs)
    else:
        if not inp.exists():
            sys.exit(f"Not found: {inp}")
        convert(inp, Path(args.output) if args.output else None, **kwargs)


if __name__ == "__main__":
    main()
