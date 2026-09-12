"""Evidence-preserving Markdown presentation shared by writing and revision."""

import re


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
                citations = re.findall(r"\[(?:S\d+|[a-f0-9]{64})[^\]]*\]", cell)
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
    date = value("document_date")
    return f"{alias} · {issuer} · {title}" + (f" · {date}" if date else "")
