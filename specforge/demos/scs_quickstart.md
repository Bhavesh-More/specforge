# Speculative Consistency Sampling (SCS) — Quickstart

This quickstart demonstrates how to call the Speculative Consistency Sampling (SCS)
feature added under `specforge/sampling`. It shows installation steps, a minimal
Python usage snippet, how to run the provided demo, and test commands.

## Requirements

- Python 3.11+
- Ollama running locally on `http://localhost:11434` (optional for tests)

Install the Python dependencies (use your project's virtualenv):

```bash
pip install httpx numpy
```

Pull the local embedding model (one-time):

```bash
# ollama CLI
ollama pull nomic-embed-text
ollama pull llama3.1:8b  # recommended default for the demo
```

The demo needs both an embedding model and a generation model. If you only have
`nomic-embed-text` installed, the demo will stop with a clear message telling
you to pull a text-generation model.

## Minimal Python usage

This example uses the high-level `SCSExecutor` API. It returns a
`SCSGenerationResult` object you can inspect for `bypassed`, `should_escalate`,
and the final `text`.

```python
import asyncio
from specforge.sampling import SCSConfig, SCSExecutor

async def run():
    cfg = SCSConfig()
    exec = SCSExecutor(cfg)

    try:
        res = await exec.generate(
            model="llama3.1:8b",
            prompt="Explain cache invalidation trade-offs for a microservice",
            node_type="reason_analysis",
            max_tokens=300,
        )

        if res.bypassed:
            print("SCS bypassed — plain generation result:")
            print(res.text)
        elif res.should_escalate:
            print("Low SCS confidence — escalate to fallback path")
            print(res.scs_result.confidence)
        else:
            print("SCS-guided output (prefix chosen + continuation):")
            print(res.text)

    finally:
        await exec.close()

asyncio.run(run())
```

Notes:
- `bypassed == True` means `n_for_node_type(node_type)` chose `1` and SCS was skipped.
- `should_escalate == True` means centroid confidence < `SCSConfig.confidence_threshold`.
- `res.scs_result.best_draft.text` contains the prefix chosen as centroid.

## Run the demo (requires Ollama)

```bash
python -m specforge.demos.scs_demo
```

The demo prints the parallel drafts, an ASCII similarity heatmap, the centrality
bars, and runs a full generation using the chosen prefix (unless confidence is
too low).

The demo auto-selects an installed generation-capable Ollama model. If
`SPECFORGE_SCS_MODEL` is set, it will prefer that model; otherwise it falls back
to the first installed non-embedding model reported by `ollama /api/tags`.

## Unit tests (no Ollama required)

Run only the narrow SCS unit tests (they mock out HTTP calls):

```bash
pytest tests/test_scs.py -v
```

## Integration notes

- The atomic executor was updated to attempt SCS before the plain Ollama call.
  If SCS returns a high-confidence result, its `text` is returned directly.
  If SCS fails or indicates escalation, the original Ollama code path continues.
- You can tune behavior by adjusting `SCSConfig` (e.g. `n_drafts`,
  `confidence_threshold`, `outlier_suppression_factor`).

## Troubleshooting

- If embeddings are missing, pull `nomic-embed-text` with the Ollama CLI.
- If you see connection errors, verify Ollama is running and reachable at the
  configured `ollama_base_url`.

---

If you'd like, I can also add a short example that integrates SCS into your
executor call flow with an explicit fallback to `adversarial_triad` for
low-confidence cases.
