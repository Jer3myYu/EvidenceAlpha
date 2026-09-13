"""Evidence-preserving Markdown presentation shared by writing and revision."""

import re

from evidencealpha import documents


def table_notes(body: str) -> str:
    """Move table citations to keyed notes without deleting supporting text."""
    lines = body.splitlines()
    output = []
    index = 0
    number = 0
    section = "资料比较"
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            if lines[index].startswith("##"):
                section = lines[index].lstrip("# ").strip()
            output.append(lines[index])
            index += 1
            continue
        number += 1
        if not any(re.match(r"\*?\*?表\s*\d", x) for x in output[-3:]):
            output.extend([f"**表 {number} · {section}**", ""])
        notes = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            cells = lines[index].strip().split("|")[1:-1]
            amended = []
            for cell in cells:
                citations = re.findall(
                    r"\[(?:S\d+|[a-f0-9]{64})[^\]]*\]" r"|【[^】]*】", cell
                )
                clean = cell
                for citation in citations:
                    clean = clean.replace(citation, "")
                commentary = ""
                if len(clean) > 80 and "；" in clean:
                    clean, commentary = clean.split("；", 1)
                if citations or commentary:
                    key = f"T{number}.{len(notes) + 1}"
                    joined = " ".join(citations)
                    notes.append(f"注 {key}：{commentary} {joined}")
                    clean = clean.strip() + f"（注{key}）"
                amended.append(clean.strip())
            output.append("| " + " | ".join(amended) + " |")
            index += 1
        if notes:
            output.extend(["", *[n + "\n" for n in notes]])
    return "\n".join(output) + "\n"


def source_label(alias: str, context: dict) -> str:
    """Use annotated identity without inferring publication dates."""

    def value(key: str) -> str:
        item = context.get(key)
        return item.get("value", "") if isinstance(item, dict) else item or ""

    issuer = value("issuer") or "机构未核实"
    title = value("title") or "文档标题未核实"
    if title.startswith(issuer):
        title = title[len(issuer) :].lstrip(" ·—-：:")
    date = value("document_date")
    return f"{alias} · {issuer} · {title}" + (f" · {date}" if date else "")


def citation_pages(
    body: str, mapping: dict, store: documents.SourceStore
) -> tuple[str, dict]:
    """Add verified PDF page locators without certifying claim entailment."""
    locations = {}

    def amend(match: re.Match) -> str:
        citation = match[0]
        aliases = set(re.findall(r"\bS\d+\b", citation))
        if len(aliases) != 1 or "PDF" in citation:
            return citation
        alias = next(iter(aliases))
        source_id = mapping.get(alias)
        if not source_id:
            return citation
        pages = set()
        for start, end in re.findall(r"c(\d+)(?:[–—-]c?(\d+))?", citation):
            last = int(end or start)
            if last - int(start) > 500 or last < int(start):
                return citation
            for number in range(int(start), last + 1):
                chunk_id = f"c{number}"
                try:
                    original = store.open_source(source_id, chunk_id)
                except (ValueError, KeyError):
                    locations[f"{alias} {chunk_id}"] = {"status": "unresolved"}
                    return citation
                found = sorted(
                    {
                        s["page"]
                        for s in original.get("spans", [])
                        if s.get("page") is not None
                    }
                )
                locations[f"{alias} {chunk_id}"] = {"pages": found}
                pages.update(found)
        if not pages:
            return citation
        label = "、".join(str(p) for p in sorted(pages))
        return citation[:-1] + f"；PDF第{label}页]"

    return re.sub(r"\[[^\]\n]*\bS\d+\b[^\]\n]*\](?!\()", amend, body), locations


def resolve_declared_sources(
    body: str, source_ids: list[str]
) -> tuple[str, dict]:
    """Bind explicitly declared report aliases before exporter numbering.

    Abbreviated hashes must resolve uniquely. A declared multi-source alias
    expands to all its declared originals; it is never silently assigned to one.
    """
    declarations = {}
    pattern = re.compile(r"(?m)^[-*]\s+\*\*(S\d+)\*\*[：:]([^\n]+)$")
    for match in pattern.finditer(body):
        alias, line = match.groups()
        references = []
        for prefix, suffix in re.findall(
            r"([a-f0-9]{6,64})(?:…|\.\.\.)([a-f0-9]{3,64})", line
        ):
            found = [
                sid
                for sid in source_ids
                if sid.startswith(prefix) and sid.endswith(suffix)
            ]
            if len(found) != 1:
                raise ValueError(
                    "Source abbreviation is unresolved or ambiguous"
                )
            references.extend(found)
        references.extend(re.findall(r"\b[a-f0-9]{64}\b", line))
        if references:
            if not set(references) <= set(source_ids):
                raise ValueError(
                    "Source declaration references unknown original"
                )
            value = list(dict.fromkeys(references))
            if alias in declarations and declarations[alias] != value:
                raise ValueError("Conflicting source alias declarations")
            declarations[alias] = value
    if not declarations:
        return body, declarations

    def expand(match: re.Match) -> str:
        alias, locator = match.groups()
        if alias not in declarations:
            raise ValueError(
                "Citation alias missing from explicit declarations"
            )
        return "；".join(
            sid + (":" + locator if locator else "")
            for sid in declarations[alias]
        )

    def citation(match: re.Match) -> str:
        return re.sub(r"\b(S\d+)(?::([c\d,–—-]+))?\b", expand, match[0])

    body = re.sub(r"\[[^\]\n]*\bS\d+\b[^\]\n]*\](?!\()", citation, body)
    body = pattern.sub(
        lambda match: match[0].replace(
            "**" + match[1] + "**",
            "**" + "；".join(declarations.get(match[1], [match[1]])) + "**",
            1,
        ),
        body,
    )
    return body, declarations
