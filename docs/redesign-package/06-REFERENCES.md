# Sources and interpretation

> Model profiles and numerical execution limits are defined once in `07-LOW-QUOTA-OVERRIDE.md`. Stage 1 ends at the mandatory fresh-session boundary in `02-STAGE-1-BUILD.md`.

Reference list retained from package preparation; this consistency pass did not revalidate external pages. These sources inform choices; they do not establish access in the user's account or a benchmark for EvidenceAlpha.

- [Codex models and reasoning effort](https://learn.chatgpt.com/docs/models): lists gpt-5.6-sol and medium reasoning; higher effort generally spends more time/tokens. We select Sol medium as an initial reviewer configuration, not a measured optimum. Actual access depends on client/account.
- [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk): programmatic local Codex threads; current Python and TypeScript interfaces. Verify installed SDK support rather than assuming old code samples still apply.
- [Codex authentication](https://learn.chatgpt.com/docs/auth): subscription and API authentication are distinct. Do not infer unrestricted API access from a ChatGPT subscription.
- [OpenAI Agents SDK quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart): ordinary API-backed agents use configured model access/API credentials; this package's reviewer instead controls local Codex.
- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview): built-in tools, agent loop, sessions, hooks and subagents. The documented third-party subscription-login restriction means a supported local setup must be established, not assumed from historical project notes.
- [Anthropic multi-agent research architecture](https://www.anthropic.com/engineering/multi-agent-research-system): agents assess sources during research and use a citation stage. Its single-call judge discussion concerns evaluation, not proof of a mandatory runtime factual-review architecture. This redesign is our engineering proposal, not a clone of private internals.
- [Anthropic contextual retrieval](https://www.anthropic.com/engineering/contextual-retrieval): generated chunk-specific context before indexing, alongside original text. This motivates selective enrichment; it does not justify replacing evidence with summaries or promising the same retrieval gains.
- [Docling chunking](https://docling-project.github.io/docling/concepts/chunking/) and [document representation](https://docling-project.github.io/docling/concepts/docling_document/): structural chunks, table handling and available provenance/layout. Docling is a candidate library, not a mandatory heavy dependency.
- [RAPTOR paper](https://arxiv.org/abs/2401.18059): hierarchical summary retrieval. Recursive summary trees are deliberately deferred in this first implementation.
- [Evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices): task-specific tests, logging and human-calibrated judgments support stage replay and small targeted evaluations. A GPT review is evidence to investigate, not unquestionable ground truth.

## Diagram interpretation

Green: SDK agent/tool loop; color does not identify a model vendor. Purple: bounded LLM contextualization. Gray: deterministic application code. Teal: stored evidence/RAG. Gold: report artifact/delivery. Diagram boxes denote responsibilities, not necessarily separate model calls.

Both PNGs show the default all-GPT profile; the preferred profile substitutes Claude for lead/research workers. GPT-5.5 rehearsals are development tests, not the default production model. The architecture PNG specifies the GPT-5.6 reviewer. The workflow's generic 'Reviewer' boxes use that same configuration. Both charts are proposed, not a representation of already deployed code. Dashed bypasses around contextualization indicate structural retrieval can proceed without LLM enrichment. Document preparation is selective; short pages can be read directly. Shared tools/RAG are available to the reviewer even when access edges are omitted for readability.
