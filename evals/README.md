# Evals

`evals/minimal_cases.jsonl` defines a small offline evaluation set for Agent Runtime Lab.
The cases focus on deterministic runtime behavior first: command routing, tool boundaries,
approval policy, persistence, workflow proposal state, and trace visibility.

Each JSONL row uses this shape:

```json
{"id":"case-id","category":"runtime","input":"...","expected_contains":["..."],"risk":"low"}
```

These cases are intentionally model-agnostic. Run them with:

```powershell
python evals/runner.py
```

The runner executes each case against an in-process `SimpleAgent`, compares every
`expected_contains` item with the returned text, and reports pass/fail results.
By default it uses an isolated temporary SQLite database and does not read `.env`.
