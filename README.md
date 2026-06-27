# MaterialHack-TheSeven

This repository is being assembled into an agentic protein-design system across
several owned branches. The current integration shape is:

- `memory/`: durable run, seed-selection, loop, rollback, and visualization
  records.
- `loop_runner/`: LangGraph optimization runner after `loop_0`.
- `app/`: runnable composition package that creates WF-style pre-loop seeds,
  persists the selected seed as `loop_0`, and hands the run to the loop runner.
- `BOLTZ_MODELS.md`: model-usage guidance for Boltz-family generation and
  evaluation adapters.

The app is currently runnable with deterministic stubs. The real screener should
come from the `TRS` branch, and the verifier remains an adapter slot.

Run the integration app from the repository root:

```bash
PYTHONPATH=memory/src:loop_runner/src:app/src \
python -m materialhack_agent \
  "design a protein that binds Zn2+ at pH 5 and can polymerize" \
  --seed-count 5 \
  --loops 2
```
