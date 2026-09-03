"""Independent verification of the synthesised answer.

The synthesis writes the final answer; nothing in Phases 1-7 reads it
afterwards. This module checks it, in two layers that never mix:

- deterministic Python for what must not depend on prose: every
  citation in the answer must be an ``[S#]`` that exists in the source
  registry (``check_citations``);
- one structured model call, independent of the synthesis, for the
  judgements: claim support, conflicting evidence, source quality
  (Phase 8.2).

The workflow (``research.workflow``) decides what to do with the result.
"""

import re

from research import sources as sources_module

# A citation is one or more labels inside one pair of brackets, as the
# synthesis writes them: [S1], [S1, S2]; [S1][S2] is two citations.
# Any other bracketed text is prose and is left alone.
_CITATION = re.compile(r"\[([SDW]\d+(?:\s*,\s*[SDW]\d+)*)\]")


def cited_labels(answer: str) -> list[str]:
    """Return every citation label in the answer, in order, repeats kept."""
    labels: list[str] = []
    for match in _CITATION.finditer(answer):
        labels.extend(part.strip() for part in match[1].split(","))
    return labels


def check_citations(
    answer: str, sources: dict[str, sources_module.SourceRecord]
) -> list[str]:
    """Return one sentence per invalid citation in the answer.

    A valid citation is an ``[S#]`` present in the registry. ``[D#]``
    and ``[W#]`` are the tools' round-local labels and never valid in a
    final answer; an unknown ``[S#]`` cites nothing.

    Args:
      answer: The synthesised answer text.
      sources: The graph-level source registry.

    Returns:
      The issues, one per distinct invalid label in first-seen order;
      empty when every citation is valid or there are none.
    """
    issues: list[str] = []
    for label in dict.fromkeys(cited_labels(answer)):
        if label[0] in "DW":
            issues.append(f"[{label}] is a round-local label, not a source.")
        elif label not in sources:
            issues.append(f"[{label}] is not a known source.")
    return issues
