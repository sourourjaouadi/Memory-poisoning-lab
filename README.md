# Memory Poisoning Lab

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](https://github.com/yourorg/memory-poisoning-lab/actions)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Memory Poisoning Lab** is an educational research environment for studying memory‑poisoning attacks and defenses in stateful LLM agents. It provides a lightweight, framework‑free codebase that makes every step of the agent's perception‑recall‑act‑remember loop fully observable.

---

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Running Attacks](#running-attacks)
- [Evaluation Harness](#evaluation-harness)
- [Inspecting Memory](#inspecting-memory)
- [Docker Support](#docker-support)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture Overview
```
memory-poisoning-lab/
├── agent/                # Core agent loop & LLM client abstraction
│   ├── config.py         # Runtime settings
│   ├── core.py           # Perceive → Recall → Act → Remember
│   ├── llm.py            # Swappable LLM back‑ends (OpenAI, Anthropic, Ollama, mock)
│   └── logger.py         # Structured JSONL logging
├── memory/               # SQLite + Chroma persistence layer
│   ├── schema.py         # Provenance data model
│   ├── structured_store.py
│   ├── vector_store.py
│   └── manager.py
├── tools/                # Mock business tools (invoice, ticket, …)
├── attacks/              # Phase 1 attack payloads
├── defenses/             # Phase 2 defenses & sanitizers
├── eval/                 # Phase 3 evaluation harness (ASR benchmark)
├── logs/                 # JSONL event logs
├── data/                 # SQLite DB & Chroma vectors
├── tests/                # Smoke tests
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── main.py               # Interactive CLI entry point
```
The hand‑rolled design keeps prompt construction, memory writes, and tool dispatch fully visible for security research.

---

## Quick Start
### 1. Clone & Set Up a Virtual Environment
```bash
git clone https://github.com/yourorg/memory-poisoning-lab.git
cd memory-poisoning-lab
python -m venv .venv
.\\.venv\\Scripts\\activate   # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```
### 2. Run the Test Suite
```bash
pytest -v tests/
```
### 3. Start the Interactive Agent
```bash
python main.py --session-id alice           # Mock LLM (no API key)
python main.py --provider ollama --session-id bob   # Real LLM via Ollama
```
---

## Running Attacks
Phase 1 attacks are invoked via the `attacks.run_attack` module. Example for a direct payment‑reroute attack:
```bash
python -m attacks.run_attack \
    --type direct \
    --config-name payment_reroute \
    --provider ollama \
    --customer-id CUST-402 \
    --plant-session-id plant_demo \
    --trigger-session-id trigger_demo
```
Supported attack types:
- **direct** – plant a malicious message via a single chat turn.
- **indirect** – plant via a tool‑output turn.
- **sleeper** – plant a delayed payload that activates on a later trigger.

---

## Evaluation Harness
The `eval/run_evaluation.py` script runs systematic benchmarks across all attack types.
```bash
# Run a full benchmark (10 runs per attack type)
python -u -m eval.run_evaluation --type all --runs 10 --provider ollama
```
Result files are written to `eval/results/` and contain fields such as `customer_id`, `stored`, `recalled`, and `influenced_tool_call`.

---

## Inspecting Memory
Use the helper script to query persistent memory stores:
```bash
# List all memory entries
python inspect_memory.py

# Filter by customer ID
python inspect_memory.py --customer-id CUST-402

# Show a specific entry
python inspect_memory.py --show <entry_id>
```
Both SQLite (`data/memory.db`) and Chroma (`data/chroma/`) are persisted across runs.

---

## Docker Support
A containerised workflow is provided for reproducible environments.
```bash
# Interactive mode
docker compose run --rm agent

# Detached mode (background)
docker compose up -d
```
Data volumes (`./data` and `./logs`) are bind‑mounted, so memory survives container restarts.

---

## Contributing
Contributions are welcome! Fork the repository, create a feature branch, and submit a pull request. Follow the existing code style and run the full test suite before opening a PR.

---

## License
This project is licensed under the MIT License – see the [LICENSE](LICENSE) file for details.

---

*© 2026 Memory Poisoning Lab – Educational AI Security Research*
