"""Process boundary for deadline-bound acquisition, without model calls."""

import json
import pathlib
import sys

from evidencealpha import artifacts
from evidencealpha import budget
from evidencealpha import config
from evidencealpha import documents
from evidencealpha import tools


def main() -> None:
    """Execute one metered acquisition; the parent owns process cancellation."""
    value = json.load(sys.stdin)
    settings = config.Settings(**value["settings"])
    evidence = tools.EvidenceTools(
        documents.SourceStore(
            pathlib.Path(value["store"]), settings.chunk_characters
        ),
        settings,
        "live",
        (
            budget.ExecutionLedger(pathlib.Path(value["ledger"]), settings)
            if artifacts.read(pathlib.Path(value["ledger"]))["limits"].get(
                "policy"
            )
            == "overall-controls-v2"
            else budget.Ledger(pathlib.Path(value["ledger"]))
        ),
    )
    try:
        result = evidence.call(value["name"], value["arguments"])
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"error": str(exc), "type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
