"""Sourced data figures and Markdown/PDF export, independent of research."""

import html
import io
import json
import os
import pathlib
import re
import subprocess
import unicodedata

import bs4
import markdown_it
import pymupdf

from evidencealpha import artifacts
from evidencealpha import layout

CSS = layout.CSS


def figures(
    specs: list[dict], folder: pathlib.Path, source_ids: set[str]
) -> list[dict]:
    """Generate figures from explicit data, preserving inputs and generator."""
    result = []
    for index, spec in enumerate(specs, 1):
        required = (
            "title",
            "caption",
            "source_ids",
            "period",
            "unit",
            "caveats",
        )
        if any(key not in spec for key in required):
            raise ValueError("Figure lacks provenance/period/unit/caption")
        if not spec["source_ids"] or not set(spec["source_ids"]).issubset(
            source_ids
        ):
            raise ValueError("Figure references unknown sources")
        directory = folder / "figures"
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / f"figure-{index}"
        artifacts.write(base.with_suffix(".json"), spec)
        if spec.get("kind") == "diagram":
            nodes = spec["nodes"]
            # DOT quoting is JSON-compatible for these labels, never shell code.
            lines = [
                "digraph G {",
                # Long horizontal chains became unreadable at page width.
                (
                    "graph [rankdir=TB];"
                    if len(nodes) > 5
                    else "graph [rankdir=LR];"
                ),
                'node [shape=box, style=rounded, fontname="sans-serif"];',
            ]
            lines.extend(f"{json.dumps(n, ensure_ascii=False)};" for n in nodes)
            for left, right in spec["edges"]:
                if left not in nodes or right not in nodes:
                    raise ValueError("Diagram edge references unknown node")
                lines.append(
                    f"{json.dumps(left, ensure_ascii=False)} -> "
                    f"{json.dumps(right, ensure_ascii=False)};"
                )
            lines.append("}")
            dot = base.with_suffix(".dot")
            artifacts.write(dot, "\n".join(lines))
            subprocess.run(
                ["dot", "-Tpng", str(dot), "-o", str(base.with_suffix(".png"))],
                check=True,
                timeout=20,
            )
            code = dot.name
        else:
            os.environ.setdefault(
                "MPLCONFIGDIR", str(directory.resolve() / ".mpl-cache")
            )
            import matplotlib  # pylint: disable=import-outside-toplevel

            matplotlib.use("Agg")
            # Optional plotting imports are local to figure generation.
            # pylint: disable=import-outside-toplevel
            import matplotlib.pyplot as plt

            if len(spec["labels"]) != len(spec["values"]):
                raise ValueError("Figure labels and values differ in length")
            pairs = [
                (label, value)
                for label, value in zip(spec["labels"], spec["values"])
                if value is not None
            ]
            if not pairs:
                raise ValueError("No observed values to plot")
            font_path = pathlib.Path(layout.fonts(directory)["regular"]["file"])
            import matplotlib.font_manager as fm

            font = fm.FontProperties(fname=str(font_path))
            fig, axis = plt.subplots(figsize=(8, 4), layout="constrained")
            try:
                bars = axis.bar(
                    [p[0] for p in pairs],
                    [p[1] for p in pairs],
                    color="#176b87",
                )
                axis.bar_label(
                    bars,
                    labels=[f"{p[1]:,.2f}" for p in pairs],
                    padding=4,
                    fontproperties=font,
                )
                axis.margins(y=0.16)
                axis.set_ylabel(spec["unit"], fontproperties=font)
                axis.set_title(spec["title"], fontproperties=font)
                for label in axis.get_xticklabels():
                    label.set_fontproperties(font)
                axis.spines[["top", "right"]].set_visible(False)
                fig.savefig(base.with_suffix(".png"), dpi=160)
            finally:
                plt.close(fig)
            code = "generator.py"
            artifacts.write(
                directory / code, pathlib.Path(__file__).read_bytes()
            )
        result.append(
            {
                **spec,
                "path": f"figures/{base.name}.png",
                "input": f"figures/{base.name}.json",
                "code": f"figures/{code}",
            }
        )
    artifacts.write(folder / "figures.json", result)
    return result


def export(markdown_path: pathlib.Path) -> dict:
    """Render the exact Markdown."""
    text = markdown_path.read_text(encoding="utf-8")
    parser = markdown_it.MarkdownIt("commonmark", {"html": False}).enable(
        "table"
    )
    body = parser.render(text)
    soup = bs4.BeautifulSoup(body, "html.parser")
    for image in soup.find_all("img"):
        path = artifacts.contained(markdown_path.parent, image["src"])
        if not path.is_file():
            name = image["src"]
            raise ValueError(f"Missing report asset: {name}")
        pixmap = pymupdf.Pixmap(str(path))
        scale = min(495 / pixmap.width, 320 / pixmap.height, 1)
        image["style"] = (
            f"width: {pixmap.width * scale}pt; "
            f"height: {pixmap.height * scale}pt;"
        )
    body = str(soup)
    artifacts.write(
        markdown_path.with_suffix(".html"), f"<style>{CSS}</style>{body}"
    )
    pdf_path = markdown_path.with_suffix(".pdf")
    status = {
        "markdown": str(markdown_path),
        "markdown_hash": artifacts.digest(text.encode()),
        "pdf": None,
        "pdf_status": "pending",
    }
    buffer = io.BytesIO()
    diagnostics = {}
    try:
        payload, pagination = layout.pdf(soup, markdown_path.parent)
        buffer.write(payload)
        diagnostics.update(pagination)
        with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as document:
            packed = re.sub(
                r"[\s\u200b]",
                "",
                unicodedata.normalize(
                    "NFKC", "".join(page.get_text() for page in document)
                ),
            )
            diagnostics["extracted_text"] = packed
            diagnostics["pages"] = len(document)
            # Detect visible omissions in body/table text; this is
            # not semantic review.
            for image in soup.find_all("img"):
                image.decompose()
            for node in soup.find_all(string=True):
                fragment = re.sub(
                    r"[\s\u200b]",
                    "",
                    unicodedata.normalize("NFKC", html.unescape(str(node))),
                )
                if fragment and fragment not in packed:
                    diagnostics["missing_fragment"] = fragment
                    raise ValueError(f"PDF omitted text: {fragment[:60]}")
            if len(document) == 0:
                raise ValueError("PDF contains no pages")
            artifacts.write(pdf_path, document.tobytes(deflate=True))
            document[0].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(
                str(markdown_path.with_suffix(".preview.png"))
            )
        status.update(
            pdf=str(pdf_path),
            pdf_status="complete",
            pages=diagnostics["pages"],
            **pagination,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        status["error"] = str(exc)
        status["pdf_status"] = "failed"
        if buffer.getvalue():
            rejected = markdown_path.with_name(
                markdown_path.stem
                + ".rejected-"
                + artifacts.digest(buffer.getvalue())[:12]
                + ".pdf"
            )
            artifacts.write(rejected, buffer.getvalue())
            artifacts.write(
                rejected.with_suffix(".json"),
                {
                    **diagnostics,
                    "error": str(exc),
                    "markdown_hash": status["markdown_hash"],
                    "pdf_hash": artifacts.digest(buffer.getvalue()),
                },
            )
            status["rejected_pdf"] = str(rejected)
        # A prior PDF must not be mistaken for the new canonical version.
        if pdf_path.exists():
            pdf_path.rename(pdf_path.with_name(pdf_path.stem + ".previous.pdf"))
    artifacts.write(markdown_path.with_suffix(".render.json"), status)
    return status
