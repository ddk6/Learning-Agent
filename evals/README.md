# Evals

`evals/minimal_cases.jsonl` defines a small offline evaluation set for Agent Runtime Lab.
The cases focus on deterministic runtime behavior first: command routing, tool boundaries,
approval policy, persistence, workflow proposal state, and trace visibility.

Each JSONL row uses this shape:

```json
{"id":"case-id","category":"runtime","input":"...","expected_contains":["..."],"risk":"low"}
```

These cases are intentionally model-agnostic. A future eval runner can execute them against
`python -m app.main` or an in-process `SimpleAgent`, then compare `expected_contains` with
the returned text and persist pass/fail results as AgentOps metrics.
