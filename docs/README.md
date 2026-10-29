# MCRAR documentation

Start with the [README](../README.md) for what MCRAR is and how to run it, and
[NOTICE.md](../NOTICE.md) for the licences.

## Using MCRAR

- [llm.md](llm.md): the optional LLM. Providers, setup, what is sent, cost and fallback.
- [labelling.md](labelling.md): labelling game scenes: what a label means and the workflow.

## How the ML works

- [model_card.md](model_card.md): the tag models (genre, mood/theme, valence/arousal, game
  scenes): data, splits, metrics, which one is selected and why.
- [embedder_bakeoff.md](embedder_bakeoff.md): how CLAP was chosen over GLAP and MuQ-MuLan
  (benchmarks and blind listening ratings).

## Developing

- [dev-setup.md](dev-setup.md): the project-local toolchain, daily commands, where things live,
  API keys.
- [api.md](api.md): the local HTTP API that the UI uses, its behaviour and its security model.
- [AGENTS.md](../AGENTS.md): rules for coding agents (and a short version for humans).

## Project record

The working record of how MCRAR was built during ShiftKey Labs' Build It! Machine Learning
program (Fall 2026). These are kept for transparency. They describe decisions as they were made,
so older sections can be superseded by newer ones.

- [STATUS.md](STATUS.md): the current state, every decision with its reasons, open items and
  follow-ups. Read this first to see where the project is.
- [PLAN.md](PLAN.md): the original plan (2026-10-11), with dated notes where reality diverged.
- [handover/](handover/): the specs given to the collaborator, as delivered:
  [M3b tagging](handover/M3b-tagging.md) and [M9 labelling](handover/M9-labelling.md).
