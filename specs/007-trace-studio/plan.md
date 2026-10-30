# Implementation

Reuse FastAPI, SSE, native DOM and existing evidence/ranking views. Replace sidebar/card navigation with a compact composer, connected graph and stage inspector. Use expandable JSON trees for recorded payloads and an allowlisted AST symbol registry for current source excerpts. Record callsites and SHA256 at span start without making observability a pipeline dependency. Expose only filtered business input from known model purposes; no raw prompts/provider text. Old traces retain their actual data and get an explicit provenance caveat.

Validation: offline suite, syntax/lint, real replay in the local browser at wide/narrow viewports. No paid model smoke required because pipeline semantics are unchanged.

S06–07 clarification: extend the same source registry with function roles and a metadata-only component map. The browser uses this registry for node labels, inspector file references and a full code-map table. A read-only catalog endpoint uses the published database catalog with an explicit as_of; current DB results are labeled separately from recorded trace metadata. Local original file presence is checked only at the conventional managed raw-file path, never served through arbitrary paths. No reranker/provider configuration change.
