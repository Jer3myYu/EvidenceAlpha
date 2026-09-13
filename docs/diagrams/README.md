# Diagram assets

`architecture.png` and `workflow.png` are illustrated documentation assets,
regenerated using the user's supplied visual reference. The reference provided
visual styling only; legacy technologies and roles were not adopted.

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

Previous PNGs remain locally in `.local/diagram-previous-20260912/`.
