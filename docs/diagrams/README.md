# Diagram assets

`architecture.png` and `workflow.png` are illustrated documentation assets,
showing the current conceptual role and evidence workflow. Optional hybrid
retrieval details are described in [Retrieval](../RETRIEVAL.md).

The companion `.dot` files preserve the earlier editable topology diagrams.
They do not generate the illustrated PNGs. To render a separate topology preview:

```bash
dot -Tpng -Gdpi=150 docs/diagrams/architecture.dot -o /tmp/evidencealpha-architecture-topology.png
dot -Tpng -Gdpi=150 docs/diagrams/workflow.dot -o /tmp/evidencealpha-workflow-topology.png
```

The illustrated architecture is a conceptual module overview. Arrows between
roles and shared infrastructure are not a concurrency or strict execution-order
specification. The workflow shows conditional correction paths; actual admission
and remaining limits can leave a partial result. The written module guide and
runtime contracts govern detailed behavior.

These assets are tracked documentation. Generated previews and historical
versions remain local; the written guides govern detailed runtime behavior.
