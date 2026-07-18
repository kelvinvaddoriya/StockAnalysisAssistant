"""
Bourse multi-agent "analyst desk".

v1 shape:  supervisor → [fundamentals ‖ news ‖ market] → synthesizer

This package holds the agent layer only — graph nodes, per-domain prompts,
shared market-data tools, and model factories. It is deliberately free of any
FastAPI / SSE / Supabase concerns so it can be imported and tested in isolation.

Build status (see docs / plan):
  step 1 ✅  state schema + shared tools + specialist factories  ← this commit
  step 2 ⬜  supervisor (routing / fast-path)
  step 3 ⬜  synthesizer (merge + self-check, streams C1 DSL)
  step 4 ⬜  StateGraph wiring (fan-out / fan-in + checkpointer)
  step 5 ⬜  SSE integration in main.py (status thinkitems + gated content)
"""
