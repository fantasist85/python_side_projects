#!/usr/bin/env python3
"""
doc2md  —  Unified CLI for functional-safety document → Markdown conversion.

Sub-commands
────────────
  excel   Single .xlsx file conversion
  word    Single .docx file conversion
  scan    Convert ALL .xlsx and .docx files under a directory tree in-place.
          Output .md is placed alongside the source file (same path, same name).

Examples
────────
  doc2md.exe excel input.xlsx
  doc2md.exe excel input.xlsx -o output.md
  doc2md.exe excel ./specs/ --batch --output-dir ./md/

  doc2md.exe word  input.docx
  doc2md.exe word  input.docx -o output.md
  doc2md.exe word  ./specs/ --batch --output-dir ./md/

  doc2md.exe scan  C:\\FuSa\\ProjectDocs
  doc2md.exe scan  C:\\FuSa\\ProjectDocs --dry-run
  doc2md.exe scan  C:\\FuSa\\ProjectDocs --skip-existing
"""

from __future__ import annotations

import logging
import sys
import textwrap
import argparse
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Version
# ──────────────────────────────────────────────────────────────────────────────

__version__ = "1.3.0"


# ──────────────────────────────────────────────────────────────────────────────
# Scan statistics  (replaces nonlocal counter pattern)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScanStats:
    """Accumulates conversion results for the scan sub-command."""
    ok:      int                    = 0
    skipped: int                    = 0
    failed:  list[tuple[Path, str]] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Sub-command: excel
# ──────────────────────────────────────────────────────────────────────────────

def _add_excel_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "excel",
        help="Convert .xlsx → Markdown (FMEA / TraceMatrix / TestCase / TSR …)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Convert an Excel (.xlsx) file to LLM-optimised Markdown.

            All sheets are rendered as GitHub-Flavoured Markdown (GFM) pipe tables.
            Merged cells (row-span and col-span) repeat the origin cell value into
            every cell of the merged region — LLMs see the actual value in every row.

            Output structure (single file)
            ──────────────────────────────
              YAML front-matter  (title, source, timestamp, sheets[] array)
              Sheet TOC          (anchor links to each sheet section)
              ## Sheet 1 / N — <name>
                > source | range | merged regions
                | col1 | col2 | … |
                | ---  | ---  | … |
                | …    | …    | … |
              ---
              ## Sheet 2 / N — <name>
              …

            For bulk conversion of an entire directory tree, use the 'scan'
            sub-command instead (preserves directory structure in-place).
        """),
        epilog=textwrap.dedent("""\
            Examples
            ────────
              doc2md excel TSR_v1.2.xlsx
              doc2md excel TSR_v1.2.xlsx -o docs/TSR_v1.2.md
              doc2md excel FMEA.xlsx --max-col-width 120 --skip-empty-rows
              doc2md excel ./specs/ --batch
              doc2md excel ./specs/ --batch --output-dir ./md/
              doc2md excel input.xlsx --no-frontmatter --no-toc
        """),
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help=(
            "Path to a .xlsx file (single-file mode), or a directory "
            "when --batch is used.  Office lock files (~$*.xlsx) are skipped."
        ),
    )
    p.add_argument(
        "-o", "--output",
        metavar="PATH",
        help=(
            "Output .md file path.  Single-file mode only.  "
            "Defaults to <INPUT>.md in the same directory as the source."
        ),
    )
    p.add_argument(
        "--batch", action="store_true",
        help=(
            "Convert ALL .xlsx files found recursively under INPUT.  "
            "Each .md is written next to its source file unless --output-dir is given."
        ),
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        help=(
            "Destination directory for --batch mode.  "
            "Files are placed flat (sub-directory structure not mirrored).  "
            "Created automatically if it does not exist."
        ),
    )
    p.add_argument(
        "--no-frontmatter", action="store_true",
        help="Omit YAML front-matter block at the top of the output.",
    )
    p.add_argument(
        "--no-toc", action="store_true",
        help="Omit the Sheet TOC anchor-link block.",
    )
    p.add_argument(
        "--max-col-width", type=int, default=None, metavar="N",
        help=(
            "Truncate cell text to N characters.  Applied to raw content BEFORE "
            "<br>/pipe-escape markup, so N reflects actual content length (default: unlimited)."
        ),
    )
    p.add_argument(
        "--skip-empty-rows", action="store_true",
        help="Remove rows where every cell is blank before rendering.",
    )
    p.add_argument(
        "--skip-empty-cols", action="store_true",
        help="Remove columns where every cell is blank before rendering.",
    )


def _run_excel(args: argparse.Namespace) -> None:
    # Import here to keep startup fast when using other sub-commands
    import excel2md

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
        excel2md.batch_convert(inp, out_dir, **kwargs)
    else:
        if not inp.exists():
            sys.exit(f"File not found: {inp}")
        out = Path(args.output) if args.output else None
        excel2md.convert(inp, out, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Sub-command: word
# ──────────────────────────────────────────────────────────────────────────────

def _add_word_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "word",
        help="Convert .docx → Markdown (TSR / FSR / SRS / HWR / SWR …)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Convert a Word (.docx) file to LLM-optimised Markdown.

            TSR / FSR entry tables are auto-detected and rendered as structured
            attribute blocks so LLMs can extract fields by name reliably.
            Generic tables are rendered as GFM pipe tables.

            Table classification rules
            ──────────────────────────
              TSR  : first-column keys contain ≥ 3 of:
                     id, state, requirement, asil, fhti, allocation,
                     related id, verification method, verification criteria,
                     release priority, status
              FSR  : first-column keys contain ≥ 2 of:
                     fsr, safety goal, input, output, asil
              Other → generic pipe table

            Output structure (single file)
            ──────────────────────────────
              YAML front-matter  (title, document_type, version, source)
              Section index      (indented heading tree, up to 120 entries)
              # Heading 1
              ## Heading 2
              **Bold paragraph** (sub-heading heuristic for Korean docs)
              - List item
              | pipe | table |
              **Key**: Value   ← TSR/FSR attribute block

            For bulk conversion of an entire directory tree, use the 'scan'
            sub-command instead (preserves directory structure in-place).
        """),
        epilog=textwrap.dedent("""\
            Examples
            ────────
              doc2md word TSR_v1.2.docx
              doc2md word TSR_v1.2.docx -o docs/TSR_v1.2.md
              doc2md word FSR.docx --pipe-tables
              doc2md word ./specs/ --batch
              doc2md word ./specs/ --batch --output-dir ./md/
              doc2md word input.docx --no-frontmatter --no-index
        """),
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help=(
            "Path to a .docx file (single-file mode), or a directory "
            "when --batch is used.  Office lock files (~$*.docx) are skipped."
        ),
    )
    p.add_argument(
        "-o", "--output",
        metavar="PATH",
        help=(
            "Output .md file path.  Single-file mode only.  "
            "Defaults to <INPUT>.md in the same directory as the source."
        ),
    )
    p.add_argument(
        "--batch", action="store_true",
        help=(
            "Convert ALL .docx files found recursively under INPUT.  "
            "Each .md is written next to its source file unless --output-dir is given."
        ),
    )
    p.add_argument(
        "--output-dir",
        metavar="DIR",
        help=(
            "Destination directory for --batch mode.  "
            "Files are placed flat (sub-directory structure not mirrored).  "
            "Created automatically if it does not exist."
        ),
    )
    p.add_argument(
        "--no-frontmatter", action="store_true",
        help="Omit YAML front-matter block at the top of the output.",
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
            "Disables TSR/FSR attribute-block rendering.  "
            "Useful for non-FuSa documents or when pipe format is preferred."
        ),
    )


def _run_word(args: argparse.Namespace) -> None:
    import word2md

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
        word2md.batch_convert(inp, out_dir, **kwargs)
    else:
        if not inp.exists():
            sys.exit(f"File not found: {inp}")
        out = Path(args.output) if args.output else None
        word2md.convert(inp, out, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Sub-command: scan  (NEW in v1.1.0)
# ──────────────────────────────────────────────────────────────────────────────

def _add_scan_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "scan",
        help="Convert ALL .xlsx + .docx under a directory tree (in-place)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Recursively scan a directory for .xlsx and .docx files and convert
            each one to Markdown.  The output .md file is written to the SAME
            directory as the source file, with the SAME base name.

            File mapping examples
            ─────────────────────
              docs/TSR/TSR_v1.2.xlsx  →  docs/TSR/TSR_v1.2.md
              docs/FSR/FSR_v0.9.docx  →  docs/FSR/FSR_v0.9.md
              docs/cover/cover.xlsx   →  docs/cover/cover.md

            Sub-directory structure is fully preserved; no files are moved.
            Office lock files (~$*.xlsx / ~$*.docx) are automatically excluded.

            Recommended workflow
            ────────────────────
              1. doc2md scan ./docs --dry-run          # preview what will be converted
              2. doc2md scan ./docs                    # run the full conversion
              3. doc2md scan ./docs --skip-existing    # incremental re-run (new files only)

            Exit code
            ─────────
              0  all files converted successfully (or nothing to convert)
              1  one or more files failed — suitable for CI/build pipeline checks
        """),
        epilog=textwrap.dedent("""\
            Examples
            ────────
              doc2md scan C:\\FuSa\\ProjectDocs
              doc2md scan C:\\FuSa\\ProjectDocs --dry-run
              doc2md scan C:\\FuSa\\ProjectDocs --skip-existing
              doc2md scan ./docs --no-frontmatter --skip-empty-rows
              doc2md scan ./docs --pipe-tables --no-toc --no-index
        """),
    )

    # ── Positional ────────────────────────────────────────────────────────────
    p.add_argument(
        "root",
        metavar="ROOT",
        help=(
            "Root directory to scan recursively.  "
            "All sub-folders are included.  Must be an existing directory."
        ),
    )

    # ── Scan behaviour ────────────────────────────────────────────────────────
    p.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Preview files that WOULD be converted without writing any output.  "
            "Existing .md files are flagged with [exists] in the preview list.  "
            "Always use this first on a new directory tree."
        ),
    )
    p.add_argument(
        "--skip-existing", action="store_true",
        help=(
            "Skip a source file if its corresponding .md already exists next to it.  "
            "Useful for incremental re-runs after adding new documents to the tree.  "
            "Without this flag, existing .md files are overwritten."
        ),
    )

    # ── Shared option ─────────────────────────────────────────────────────────
    p.add_argument(
        "--no-frontmatter", action="store_true",
        help="Omit YAML front-matter block from ALL outputs (both .xlsx and .docx).",
    )

    # ── Excel-specific ────────────────────────────────────────────────────────
    xg = p.add_argument_group("Excel options  (applied to .xlsx files only)")
    xg.add_argument(
        "--no-toc", action="store_true",
        help="Omit Sheet TOC anchor-link block from Excel outputs.",
    )
    xg.add_argument(
        "--max-col-width", type=int, default=None, metavar="N",
        help=(
            "Truncate Excel cell text to N characters (raw content, before markup).  "
            "Default: unlimited."
        ),
    )
    xg.add_argument(
        "--skip-empty-rows", action="store_true",
        help="Remove fully-blank rows from Excel tables before rendering.",
    )
    xg.add_argument(
        "--skip-empty-cols", action="store_true",
        help="Remove fully-blank columns from Excel tables before rendering.",
    )

    # ── Word-specific ─────────────────────────────────────────────────────────
    wg = p.add_argument_group("Word options  (applied to .docx files only)")
    wg.add_argument(
        "--no-index", action="store_true",
        help="Omit auto-generated section index block from Word outputs.",
    )
    wg.add_argument(
        "--pipe-tables", action="store_true",
        help=(
            "Render ALL Word tables as GFM pipe tables.  "
            "Disables TSR/FSR attribute-block rendering."
        ),
    )


def _collect_scan_targets(root: Path) -> tuple[list[Path], list[Path]]:
    """
    Walk *root* recursively.
    Returns (xlsx_files, docx_files) sorted by full path.
    Office lock files (~$prefix) are excluded automatically.
    """
    xlsx_files = sorted(
        f for f in root.rglob("*.xlsx")
        if not f.name.startswith("~$")
    )
    docx_files = sorted(
        f for f in root.rglob("*.docx")
        if not f.name.startswith("~$")
    )
    return xlsx_files, docx_files


def _try_convert(
    src: Path,
    root: Path,
    converter,
    kwargs: dict,
    skip_existing: bool,
    stats: ScanStats,
) -> None:
    """
    Attempt to convert *src* using *converter*.
    Updates *stats* in-place (no nonlocal variables needed).

    Output is always placed next to the source file: src_dir / src_stem.md
    """
    out = src.with_suffix(".md")

    if skip_existing and out.exists():
        logger.info("  [skip]  %s", src.relative_to(root))
        stats.skipped += 1
        return

    try:
        converter(src, out, **kwargs)
        stats.ok += 1
    except Exception as exc:          # noqa: BLE001
        logger.error("  [FAIL]  %s: %s", src.relative_to(root), exc)
        stats.failed.append((src, str(exc)))


def _run_scan(args: argparse.Namespace) -> None:
    import excel2md
    import word2md

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    xlsx_files, docx_files = _collect_scan_targets(root)
    total = len(xlsx_files) + len(docx_files)

    if total == 0:
        logger.info("No .xlsx or .docx files found under: %s", root)
        return

    # ── Dry-run: list files and exit without converting ───────────────────────
    if args.dry_run:
        logger.info("[dry-run]  root  : %s", root)
        logger.info("           xlsx  : %d file(s)", len(xlsx_files))
        logger.info("           docx  : %d file(s)", len(docx_files))
        logger.info("           total : %d file(s)\n", total)
        for f in xlsx_files:
            out = f.with_suffix(".md")
            tag = "  [exists]" if out.exists() else ""
            logger.info("  XLSX  %s%s", f.relative_to(root), tag)
        for f in docx_files:
            out = f.with_suffix(".md")
            tag = "  [exists]" if out.exists() else ""
            logger.info("  DOCX  %s%s", f.relative_to(root), tag)
        return

    # ── Build per-type kwargs ─────────────────────────────────────────────────
    excel_kwargs: dict = dict(
        add_frontmatter=not args.no_frontmatter,
        add_toc=not args.no_toc,
        max_col_width=args.max_col_width,
        skip_empty_rows=args.skip_empty_rows,
        skip_empty_cols=args.skip_empty_cols,
    )
    word_kwargs: dict = dict(
        add_frontmatter=not args.no_frontmatter,
        add_index=not args.no_index,
        force_pipe=args.pipe_tables,
    )

    # ── Conversion loop ───────────────────────────────────────────────────────
    logger.info("[scan]  root  : %s", root)
    logger.info("        xlsx  : %d file(s)", len(xlsx_files))
    logger.info("        docx  : %d file(s)", len(docx_files))
    logger.info("        total : %d file(s)\n", total)

    stats = ScanStats()

    for f in xlsx_files:
        _try_convert(f, root, excel2md.convert, excel_kwargs, args.skip_existing, stats)

    for f in docx_files:
        _try_convert(f, root, word2md.convert, word_kwargs, args.skip_existing, stats)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n%s", "=" * 56)
    logger.info("  Scan complete  —  root: %s", root)
    logger.info("  Converted : %d", stats.ok)
    if stats.skipped:
        logger.info("  Skipped   : %d  (--skip-existing)", stats.skipped)
    if stats.failed:
        logger.error("  Failed    : %d", len(stats.failed))
        for src, msg in stats.failed:
            logger.error("    x %s: %s", src.relative_to(root), msg)
    logger.info("%s", "=" * 56)

    if stats.failed:
        sys.exit(1)   # non-zero exit so build pipelines can detect failures


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Drag-and-drop  (v1.3.0)
# ──────────────────────────────────────────────────────────────────────────────

def _pause_on_windows() -> None:
    """Keep the console window open after conversion finishes (Windows .exe only).

    When doc2md.exe is launched via drag-and-drop (or a double-click), the
    console window is created by Windows and destroyed as soon as the process
    exits.  Pausing lets the user read the output before the window closes.
    This helper is a no-op on non-Windows platforms and when the process is
    run from an existing terminal (stdout is not a TTY check is intentionally
    skipped — drag-and-drop always attaches a TTY on Windows).
    """
    import os
    if os.name == "nt":
        input("\nPress Enter to close this window…")


def _detect_dragdrop(argv: list[str]) -> bool:
    """Return True when argv looks like a drag-and-drop invocation.

    Heuristic: no recognised sub-command as first positional argument and
    at least one argument that is a valid filesystem path.

    Recognised sub-commands are intentionally hard-coded so that a future
    command named after a real filename is not misclassified.
    """
    _KNOWN_SUBCOMMANDS = {"excel", "word", "scan"}
    if not argv:
        return False
    first = argv[0].lstrip("-")          # ignore leading flag-like strings
    return first not in _KNOWN_SUBCOMMANDS and Path(argv[0]).exists()


def _run_dragdrop(paths: list[str]) -> None:
    """Auto-route one or more drag-and-dropped paths to the correct converter.

    Routing rules
    ─────────────
      Directory           → scan  (converts all .xlsx + .docx underneath)
      .xlsx file          → excel (single-file conversion)
      .docx file          → word  (single-file conversion)
      Multiple files      → each file is dispatched individually (directories
                            are dispatched as scan)
      Unsupported suffix  → warning printed; file is skipped

    Default converter options (identical to calling the sub-command with no
    extra flags) are used so that drag-and-drop 'just works' without a
    terminal.  Power users should use the CLI sub-commands for fine-grained
    control.
    """
    import excel2md
    import word2md

    # ── Defaults mirroring sub-command defaults ───────────────────────────────
    excel_kwargs: dict = dict(
        add_frontmatter=True,
        add_toc=True,
        max_col_width=None,
        skip_empty_rows=False,
        skip_empty_cols=False,
    )
    word_kwargs: dict = dict(
        add_frontmatter=True,
        add_index=True,
        force_pipe=False,
    )

    ok = skipped = 0
    failed: list[tuple[str, str]] = []

    for raw in paths:
        p = Path(raw)

        if not p.exists():
            logger.warning("[skip]  Path not found: %s", raw)
            skipped += 1
            continue

        # ── Directory → scan ─────────────────────────────────────────────────
        if p.is_dir():
            logger.info("[scan]  %s", p)
            xlsx_files, docx_files = _collect_scan_targets(p)
            stats = ScanStats()
            for f in xlsx_files:
                _try_convert(f, p, excel2md.convert, excel_kwargs, False, stats)
            for f in docx_files:
                _try_convert(f, p, word2md.convert, word_kwargs, False, stats)
            ok      += stats.ok
            skipped += stats.skipped
            failed  += stats.failed
            continue

        # ── Single file ───────────────────────────────────────────────────────
        suffix = p.suffix.lower()
        out    = p.with_suffix(".md")

        if suffix == ".xlsx":
            logger.info("[excel] %s  →  %s", p.name, out.name)
            try:
                excel2md.convert(p, out, **excel_kwargs)
                ok += 1
            except Exception as exc:        # noqa: BLE001
                logger.error("[FAIL]  %s: %s", p.name, exc)
                failed.append((str(p), str(exc)))

        elif suffix == ".docx":
            logger.info("[word]  %s  →  %s", p.name, out.name)
            try:
                word2md.convert(p, out, **word_kwargs)
                ok += 1
            except Exception as exc:        # noqa: BLE001
                logger.error("[FAIL]  %s: %s", p.name, exc)
                failed.append((str(p), str(exc)))

        else:
            logger.warning("[skip]  Unsupported file type (%s): %s", suffix or "(none)", p.name)
            skipped += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 56)
    logger.info("  Done")
    logger.info("  Converted : %d", ok)
    if skipped:
        logger.info("  Skipped   : %d", skipped)
    if failed:
        logger.error("  Failed    : %d", len(failed))
        for src, msg in failed:
            logger.error("    x %s: %s", src, msg)
    logger.info("=" * 56)

    _pause_on_windows()

    if failed:
        sys.exit(1)


def main() -> None:
    # ── Drag-and-drop fast-path ───────────────────────────────────────────────
    # When the user drags one or more files / folders onto doc2md.exe, Windows
    # passes the paths directly as positional arguments with no sub-command.
    # Detect this case early and bypass argparse entirely so the user never
    # sees a "subcommand required" error message.
    if _detect_dragdrop(sys.argv[1:]):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logger.info("doc2md %s — drag-and-drop mode", __version__)
        logger.info("")
        _run_dragdrop(sys.argv[1:])
        return
    # ─────────────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(
        prog="doc2md",
        description=textwrap.dedent("""\
            ╔══════════════════════════════════════════════════════════════╗
            ║      doc2md — Functional-Safety Document → Markdown         ║
            ║         Converter for LLM-based Analysis Workflows          ║
            ╚══════════════════════════════════════════════════════════════╝

            Converts .xlsx (Excel) and .docx (Word) files to LLM-optimised
            Markdown for functional-safety document analysis:
            content review, cross-document consistency, and traceability.

            Sub-commands
            ────────────
              excel   Convert a single .xlsx file (or batch a directory)
              word    Convert a single .docx file (or batch a directory)
              scan    Convert ALL .xlsx + .docx under a directory tree in-place

            Supported document types
            ────────────────────────
              Excel : TSR, FSR, FMEA, TraceMatrix, TestCase, TestReport, generic
              Word  : TSR, FSR, SRS, HWR, SWR, Korean-English mixed specs

            Quick start
            ───────────
              doc2md excel TSR_v1.2.xlsx
              doc2md word  FSR_v0.9.docx
              doc2md scan  ./ProjectDocs --dry-run
              doc2md scan  ./ProjectDocs

            Use 'doc2md <command> --help' for per-command option details.
        """),
        epilog=textwrap.dedent("""\
            Common patterns
            ───────────────
              # Single-file conversions
              doc2md excel TSR.xlsx -o output/TSR.md
              doc2md word  FSR.docx -o output/FSR.md

              # Batch-convert one file type into a separate output directory
              doc2md excel ./specs/ --batch --output-dir ./md/
              doc2md word  ./specs/ --batch --output-dir ./md/

              # In-place bulk conversion of an entire project directory
              doc2md scan  C:\\FuSa\\ProjectDocs --dry-run       # preview first
              doc2md scan  C:\\FuSa\\ProjectDocs                 # convert all
              doc2md scan  C:\\FuSa\\ProjectDocs --skip-existing # add new files only

              # CI/CD pipeline usage (exits 1 on any failure)
              doc2md scan ./docs && echo "All converted"

            Global flag
            ───────────
              -v / --verbose   Enable DEBUG-level logging for all sub-commands
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG-level) logging output.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
    )
    subparsers.required = True

    _add_excel_parser(subparsers)
    _add_word_parser(subparsers)
    _add_scan_parser(subparsers)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.command == "excel":
        _run_excel(args)
    elif args.command == "word":
        _run_word(args)
    elif args.command == "scan":
        _run_scan(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
