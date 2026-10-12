# MCRAR

An ML music recommender for listeners and indie game developers. Describe the music you want (and add
filters such as BPM, mood or duration) and MCRAR searches royalty-free catalogs and your own folders and
asset packs, with license-safety badges and a credits export aimed at game projects. An LLM is optional
and uses your own API key.

Status: in development. Done: M0 toolchain, M1 audio analysis, M2 catalog and Jamendo/local
ingest with licensing, M3a text-to-music embeddings (CLAP by default). In progress: M3b tagging
(collaborator) and M4 search and ranking.

- Development setup (everything stays inside the repo folder): [docs/dev-setup.md](docs/dev-setup.md)
- Product and implementation plan: [docs/PLAN.md](docs/PLAN.md)
- Instructions for coding agents (Codex and others): [AGENTS.md](AGENTS.md)
- Embedding model bake-off results: [docs/embedder_bakeoff.md](docs/embedder_bakeoff.md)
- M3b/M3c handover spec: [docs/handover/M3b-tagging.md](docs/handover/M3b-tagging.md)

License: see [LICENSE](LICENSE).
