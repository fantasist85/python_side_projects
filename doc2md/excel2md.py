#!/usr/bin/env python3
"""
xlsx_to_markdown.py
===================
LLM-optimised XLSX → Markdown converter for functional safety deliverables.
(TSR / FSR / FMEA / TraceMatrix / TestCase / TestReport and similar)

Design goals
────────────
1. Single generic renderer — no document-type-specific logic.
   All sheets are rendered as GFM pipe tables regardless of content type.

2. Merged cell handling (both row-span and col-span):
   Origin cell value is REPEATED into every cell of the merged region.
   No placeholder symbols; LLM sees the actual value in every row.

3. Multi-sheet output → Option C:
   Single .md file with YAML front-matter + anchor-based Sheet TOC.
   Each sheet gets an <a id="sheet-{slug}"> anchor and a ## heading.

4. Intra-cell newlines → <br> tags so MD renderers preserve line structure.
   Pipe characters inside cell text are escaped as \\|.

5. Sheet meta-line (range, merged-region count) inserted above each table
   so LLMs can gauge table size without reading every row.

6. Batch mode: converts all .xlsx files under a directory tree.

Usage
─────
    # single file
    python xlsx_to_markdown.py input.xlsx

    # custom output path
    python xlsx_to_markdown.py input.xlsx -o output.md

    # batch (all .xlsx in a directory)
    python xlsx_to_markdown.py ./specs/ --batch [--output-dir ./md/]

    # options
    --no-frontmatter     skip YAML front-matter block
    --no-toc             skip sheet TOC block
    --max-col-width N    truncate cell text to N chars (default: unlimited)
    --skip-empty-rows    omit rows where every cell is blank
    --skip-empty-cols    omit columns where every cell is blank

Requirements
────────────
    pip install openpyxl --break-system-packages
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

import openpyxl
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Type aliases
# ──────────────────────────────────────────────────────────────────────────────

CellGrid = list[list[str]]   # grid[row_idx][col_idx] = cell text


class SheetMeta(TypedDict):
    """Typed metadata collected for each worksheet."""
    index:          int
    name:           str
    type_hint:      str
    anchor:         str
    rows:           int
    cols:           int
    merged_regions: int
    range:          str


# ──────────────────────────────────────────────────────────────────────────────
# Merge map builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_merge_map(ws: Worksheet) -> dict[tuple[int, int], tuple[int, int]]:
    """
    Return a dict mapping every (row, col) inside a merged region to the
    (origin_row, origin_col) of that region.  Uses 0-based indices internally.

    openpyxl merged_cells uses 1-based min_row/min_col/max_row/max_col.
    Conversion: 0-based start = 1-based_value - 1
                0-based end   = 1-based_value - 1  (but range() upper is exclusive,
                                so pass 1-based max directly → covers all cells)
    Example: rows 2..4 (1-based) → range(1, 4) → 1,2,3  ✓
    """
    merge_map: dict[tuple[int, int], tuple[int, int]] = {}
    for merged_range in ws.merged_cells.ranges:
        # 0-based origin of this merged region
        origin = (merged_range.min_row - 1, merged_range.min_col - 1)
        # range upper bound: 1-based max used directly because range() is exclusive
        # → covers all rows/cols from min to max inclusive in 1-based coordinates
        for r in range(merged_range.min_row - 1, merged_range.max_row):
            for c in range(merged_range.min_col - 1, merged_range.max_col):
                merge_map[(r, c)] = origin
    return merge_map


# ──────────────────────────────────────────────────────────────────────────────
# Cell value helpers
# ──────────────────────────────────────────────────────────────────────────────

def _cell_text(value: object, max_col_width: int | None) -> str:
    """
    Convert a raw openpyxl cell value to a clean string.

    · None / empty  → ""
    · Truncation applied first on the RAW string before any transformation,
      so the N-character limit reflects actual content length, not markup.
    · Intra-cell newlines (\n, \r\n) → <br>
    · Pipe characters → \\|  (GFM table escape)
    """
    if value is None:
        return ""

    text = str(value).strip()

    # Truncate on raw text BEFORE adding <br> / escape markup
    # (ensures max_col_width reflects actual content characters, not HTML tags)
    if max_col_width and len(text) > max_col_width:
        text = text[:max_col_width]

    # Normalise line endings, then convert to <br>
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>")

    # Escape pipe to avoid breaking table columns
    text = text.replace("|", "\\|")

    return text


# ──────────────────────────────────────────────────────────────────────────────
# Sheet data extraction
# ──────────────────────────────────────────────────────────────────────────────

def _extract_grid(
    ws: Worksheet,
    max_col_width: int | None,
    skip_empty_rows: bool,
    skip_empty_cols: bool,
) -> CellGrid:
    """
    Extract the worksheet into a list-of-lists of strings.

    Merged cells: every cell in a merged region gets the origin cell's value.
    Empty rows / columns removed if the corresponding skip_* flag is True.
    """
    merge_map = _build_merge_map(ws)

    # Build raw grid (0-based)
    raw: list[list[object]] = []
    for row_cells in ws.iter_rows():
        row_data: list[object] = []
        for cell in row_cells:
            r, c = cell.row - 1, cell.column - 1
            if (r, c) in merge_map:
                origin_r, origin_c = merge_map[(r, c)]
                # Fetch origin cell value directly from worksheet (1-based)
                origin_value = ws.cell(row=origin_r + 1, column=origin_c + 1).value
                row_data.append(origin_value)
            else:
                row_data.append(cell.value)
        raw.append(row_data)

    if not raw:
        return []

    # Normalise column count across all rows
    n_cols = max(len(r) for r in raw)
    for r in raw:
        while len(r) < n_cols:
            r.append(None)

    # Optional: remove fully-empty columns BEFORE converting to strings
    if skip_empty_cols:
        non_empty_cols = [
            c for c in range(n_cols)
            if any(raw[r][c] is not None and str(raw[r][c]).strip() != ""
                   for r in range(len(raw)))
        ]
        raw = [[row[c] for c in non_empty_cols] for row in raw]
        n_cols = len(non_empty_cols) if non_empty_cols else 0

    # Convert to strings
    grid: CellGrid = [
        [_cell_text(cell, max_col_width) for cell in row]
        for row in raw
    ]

    # Optional: remove fully-empty rows
    if skip_empty_rows:
        grid = [row for row in grid if any(cell != "" for cell in row)]

    return grid


# ──────────────────────────────────────────────────────────────────────────────
# GFM pipe table renderer
# ──────────────────────────────────────────────────────────────────────────────

def _render_pipe_table(grid: CellGrid) -> str:
    """
    Render a CellGrid as a GFM pipe table.

    Row 0 is treated as the header row.
    A separator line (---) is inserted after the header.
    If the grid has only one row, that row is still treated as a header
    and a separator is added (empty body).
    """
    if not grid:
        return "*(empty sheet)*"

    n_cols = max(len(row) for row in grid)

    # Pad every row to n_cols
    padded: CellGrid = []
    for row in grid:
        padded_row = list(row)
        while len(padded_row) < n_cols:
            padded_row.append("")
        padded.append(padded_row)

    # Column widths: max content width, minimum 3 for --- separator
    widths = [
        max(max(len(padded[r][c]) for r in range(len(padded))), 3)
        for c in range(n_cols)
    ]

    def _fmt_row(cells: list[str]) -> str:
        parts = [cells[i].ljust(widths[i]) for i in range(n_cols)]
        return "| " + " | ".join(parts) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"

    lines = [_fmt_row(padded[0]), sep]
    lines += [_fmt_row(row) for row in padded[1:]]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Sheet metadata extractor
# ──────────────────────────────────────────────────────────────────────────────

def _sheet_type_hint(sheet_name: str) -> str:
    """
    Derive a lowercase type hint from the sheet name for YAML front-matter.
    Pure heuristic — does NOT affect rendering logic.
    """
    name_lower = sheet_name.lower()
    keywords = [
        ("tsr",          "tsr"),
        ("fsr",          "fsr"),
        ("fmea",         "fmea"),
        ("trace",        "tracematrix"),
        ("test case",    "testcase"),
        ("testcase",     "testcase"),
        ("test report",  "testreport"),
        ("testreport",   "testreport"),
        ("test result",  "testreport"),
        ("cover",        "cover"),
        ("revision",     "revision"),
        ("change",       "revision"),
        ("index",        "index"),
        ("toc",          "index"),
    ]
    for keyword, hint in keywords:
        if keyword in name_lower:
            return hint
    return "generic"


def _slug(text: str) -> str:
    """Convert sheet name to a URL-safe anchor slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text or "sheet"


def _data_range_str(ws: Worksheet) -> str:
    """Return 'A1:XN' style range string for the worksheet's used area."""
    if ws.min_row is None:
        return "A1:A1"
    min_col_letter = get_column_letter(ws.min_column or 1)
    max_col_letter = get_column_letter(ws.max_column or 1)
    return (
        f"{min_col_letter}{ws.min_row}:"
        f"{max_col_letter}{ws.max_row}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Front-matter builder
# ──────────────────────────────────────────────────────────────────────────────

def _make_front_matter(
    source: Path,
    sheet_metas: list[SheetMeta],
) -> str:
    """Build YAML front-matter block."""
    title = source.stem.replace("_", " ")
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        "---",
        f'title: "{title}"',
        f'source: "{source.name}"',
        f'converted_at: "{now}"',
        "sheets:",
    ]
    for m in sheet_metas:
        lines += [
            f'  - index: {m["index"]}',
            f'    name: "{m["name"]}"',
            f'    type_hint: "{m["type_hint"]}"',
            f'    anchor: "{m["anchor"]}"',
            f'    rows: {m["rows"]}',
            f'    cols: {m["cols"]}',
            f'    merged_regions: {m["merged_regions"]}',
        ]
    lines += ["---", ""]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Sheet TOC builder
# ──────────────────────────────────────────────────────────────────────────────

def _make_sheet_toc(sheet_metas: list[SheetMeta]) -> str:
    """Build the Sheet TOC block that appears after front-matter."""
    lines = ["<!-- Sheet TOC -->", ""]
    for m in sheet_metas:
        lines.append(
            f'{m["index"]}. [{m["name"]}](#{m["anchor"]}) '
            f'— {m["rows"]} rows × {m["cols"]} cols'
            + (f' · {m["merged_regions"]} merged' if m["merged_regions"] else "")
        )
    lines += ["", "---", ""]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Core converter
# ──────────────────────────────────────────────────────────────────────────────

def convert(
    input_path: Path,
    output_path: Path | None = None,
    add_frontmatter: bool = True,
    add_toc: bool = True,
    max_col_width: int | None = None,
    skip_empty_rows: bool = False,
    skip_empty_cols: bool = False,
) -> Path:
    """
    Convert a single .xlsx file to a Markdown file.

    Parameters
    ----------
    input_path      : source .xlsx path
    output_path     : destination .md path (defaults to same stem as input)
    add_frontmatter : include YAML front-matter block
    add_toc         : include Sheet TOC block
    max_col_width   : truncate cell text to this many characters (None = off).
                      Truncation is applied to raw text BEFORE <br>/escape markup.
    skip_empty_rows : omit rows where every cell is blank
    skip_empty_cols : omit columns where every cell is blank
    """
    if output_path is None:
        output_path = input_path.with_suffix(".md")

    logger.info("[convert] %s  →  %s", input_path.name, output_path.name)

    # ── [1] Load workbook ────────────────────────────────────────────────────
    logger.info("  [1/4] Loading workbook …")
    wb = load_workbook(str(input_path), data_only=True, read_only=False)

    # ── [2] Per-sheet metadata pass ──────────────────────────────────────────
    logger.info("  [2/4] Collecting sheet metadata …")
    sheet_metas: list[SheetMeta] = []
    for idx, ws in enumerate(wb.worksheets, start=1):
        n_merged = len(list(ws.merged_cells.ranges))
        rows = ws.max_row  or 0
        cols = ws.max_column or 0
        sheet_metas.append(SheetMeta(
            index=idx,
            name=ws.title,
            type_hint=_sheet_type_hint(ws.title),
            anchor=f"sheet-{_slug(ws.title)}",
            rows=rows,
            cols=cols,
            merged_regions=n_merged,
            range=_data_range_str(ws),
        ))

    # ── [3] Build document sections ──────────────────────────────────────────
    logger.info("  [3/4] Converting sheets …")
    parts: list[str] = []

    if add_frontmatter:
        parts.append(_make_front_matter(input_path, sheet_metas))

    if add_toc:
        parts.append(_make_sheet_toc(sheet_metas))

    total = len(wb.worksheets)
    for meta, ws in zip(sheet_metas, wb.worksheets):
        logger.info("        Sheet %d/%d: %r …", meta["index"], total, ws.title)

        grid = _extract_grid(
            ws,
            max_col_width=max_col_width,
            skip_empty_rows=skip_empty_rows,
            skip_empty_cols=skip_empty_cols,
        )

        section_lines: list[str] = []

        # Anchor + heading
        section_lines.append(f'<a id="{meta["anchor"]}"></a>')
        section_lines.append(
            f'## 📋 Sheet {meta["index"]} / {total} — {meta["name"]}'
        )

        # Meta info line
        meta_parts = [
            f'source: `{input_path.name}`',
            f'range: `{meta["range"]}`',
        ]
        if meta["merged_regions"]:
            meta_parts.append(f'merged regions: {meta["merged_regions"]}')
        section_lines.append("> " + " | ".join(meta_parts))
        section_lines.append("")

        # Pipe table
        section_lines.append(_render_pipe_table(grid))
        section_lines.append("")
        section_lines.append("---")
        section_lines.append("")

        parts.append("\n".join(section_lines))

    # ── [4] Write output ─────────────────────────────────────────────────────
    logger.info("  [4/4] Writing output …")
    full_md = "\n".join(parts)

    # Collapse 4+ consecutive blank lines → 2
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
    """Convert all .xlsx files found recursively under *directory*.

    Office lock files (~$*.xlsx) are automatically excluded.
    """
    files = sorted(
        f for f in directory.glob("**/*.xlsx")
        if not f.name.startswith("~$")
    )
    if not files:
        logger.info("No .xlsx files found in: %s", directory)
        return

    logger.info("Found %d file(s).", len(files))
    failed: list[tuple[Path, str]] = []

    for f in files:
        if output_dir:
            out = output_dir / f.with_suffix(".md").name
        else:
            out = f.with_suffix(".md")
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
    parser = argparse.ArgumentParser(
        prog="excel2md",
        description=textwrap.dedent("""\
            ╔══════════════════════════════════════════════════════════════╗
            ║           excel2md — XLSX → Markdown Converter              ║
            ║   LLM-optimised output for functional safety deliverables   ║
            ╚══════════════════════════════════════════════════════════════╝

            Converts Excel (.xlsx) files to LLM-optimised Markdown.
            Designed for FuSa documents: TSR / FSR / FMEA / TraceMatrix /
            TestCase / TestReport and any generic tabular spreadsheet.

            Key features
            ────────────
              • All sheets rendered as GitHub-Flavoured Markdown (GFM) pipe tables
              • Merged cells (row-span & col-span): origin value repeated into
                every cell of the merged region — LLM sees the actual value in
                every row, not an empty gap
              • Multi-sheet output: single .md with YAML front-matter + Sheet TOC
                and anchor links  (e.g.  #sheet-cover,  #sheet-fmea)
              • Intra-cell newlines converted to <br> tags
              • Pipe characters inside cells escaped as \\| to protect table layout
              • Sheet metadata line (range, merged-region count) inserted above
                each table so LLMs can gauge table size at a glance
        """),
        epilog=textwrap.dedent("""\
            Output path rules
            ─────────────────
              Single-file mode  →  output defaults to <input>.md in the same folder
                                   Override with -o / --output
              Batch mode        →  each file gets its own .md next to the source
                                   Override destination root with --output-dir

            Merge-cell behaviour
            ────────────────────
              Excel merged regions have one "origin" cell with a value; the rest
              are empty.  This tool repeats the origin value into every cell of
              the region so LLMs (and human readers) always see the full value
              in each row — no blank gaps, no placeholder symbols.

            Blank-row / blank-column filtering
            ───────────────────────────────────
              --skip-empty-rows / --skip-empty-cols are applied BEFORE rendering,
              so column-width calculations reflect only visible content.

            YAML front-matter
            ─────────────────
              Emitted at the top of each output file.  Includes:
                title, source filename, conversion timestamp (UTC),
                and a sheets[] array with per-sheet metadata
                (index, name, type_hint, anchor, rows, cols, merged_regions).

            Sheet TOC
            ─────────
              Anchor-based table of contents placed just after front-matter.
              Each entry shows:  N. [Sheet Name](#anchor) — R rows × C cols
              Skip with --no-toc if the TOC is not needed downstream.

            Examples
            ────────
              # Convert a single file (output: input.md)
              python excel2md.py TSR_v1.2.xlsx

              # Specify output path
              python excel2md.py TSR_v1.2.xlsx -o docs/TSR_v1.2.md

              # Truncate long cells and remove blank rows
              python excel2md.py FMEA.xlsx --max-col-width 120 --skip-empty-rows

              # Batch-convert all .xlsx under ./specs/, outputs beside sources
              python excel2md.py ./specs/ --batch

              # Batch with separate output directory
              python excel2md.py ./specs/ --batch --output-dir ./md/

              # Minimal output (no front-matter, no TOC)
              python excel2md.py input.xlsx --no-frontmatter --no-toc
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help=(
            "Path to a .xlsx file (single-file mode), or a directory "
            "(--batch mode).  Office lock files (~$*.xlsx) are always skipped."
        ),
    )
    parser.add_argument(
        "-o", "--output",
        metavar="PATH",
        help=(
            "Output .md file path.  Single-file mode only.  "
            "Defaults to <INPUT>.md in the same directory."
        ),
    )
    parser.add_argument(
        "--batch", action="store_true",
        help=(
            "Convert ALL .xlsx files found recursively under INPUT.  "
            "Each output .md is placed next to its source file unless "
            "--output-dir is specified."
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help=(
            "Destination directory for --batch mode.  "
            "All .md files are placed flat in this directory "
            "(sub-directory structure is NOT mirrored).  "
            "Directory is created if it does not exist."
        ),
    )
    parser.add_argument(
        "--no-frontmatter", action="store_true",
        help=(
            "Omit the YAML front-matter block at the top of the output.  "
            "Useful when the .md will be embedded in a larger document."
        ),
    )
    parser.add_argument(
        "--no-toc", action="store_true",
        help=(
            "Omit the Sheet TOC block (anchor links to each sheet section).  "
            "Has no effect when --no-frontmatter is also set."
        ),
    )
    parser.add_argument(
        "--max-col-width", type=int, default=None, metavar="N",
        help=(
            "Truncate cell text to N characters.  Truncation is applied to "
            "the raw cell string BEFORE <br> / pipe-escape markup is added, "
            "so N reflects actual content characters (default: unlimited)."
        ),
    )
    parser.add_argument(
        "--skip-empty-rows", action="store_true",
        help="Remove rows where every cell is blank before rendering.",
    )
    parser.add_argument(
        "--skip-empty-cols", action="store_true",
        help="Remove columns where every cell is blank before rendering.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG-level) logging output.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    inp = Path(args.input)

    kwargs: dict = dict(
        add_frontmatter=not args.no_frontmatter,
        add_toc=not args.no_toc,
        max_col_width=args.max_col_width,
        skip_empty_rows=args.skip_empty_rows,
        skip_empty_cols=args.skip_empty_cols,
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
            sys.exit(f"File not found: {inp}")
        out = Path(args.output) if args.output else None
        convert(inp, out, **kwargs)


if __name__ == "__main__":
    main()
