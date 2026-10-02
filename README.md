# least-privilege-clinical-safety

Research code for **clinically bounded, credential-bound authorization of LLM agents acting on HL7 FHIR health records** (manuscript in preparation).

> **Status:** early feasibility pilot. Interfaces and results are not stable.

## What is here
| Path | Content |
|---|---|
| `pilot/` | Feasibility pilot: HAPI FHIR (R4) + PostgreSQL stack (`docker-compose.yml`), Synthea bundle loader with persistence check, CPU LLM speed benchmark, minimal tool-using agent with deterministic answer checks |
| `formal/tamarin/` | Tamarin models: a simplified purpose-bound mandate protocol with a counterexample (`pilot_mandate.spthy`) and its fix (`pilot_mandate_fixed.spthy`); `run_tamarin.sh` installs Tamarin 1.12.0 and Maude in a stock `ubuntu:24.04` container |
| `models/` | SHA256 manifests of the open-weight GGUF models used (weights are not stored here) |
| `synthea/` | Synthea jar checksum (jar and generated data are not stored here) |

## Requirements
- Docker
- Python ≥ 3.11 with `httpx`
- No GPU and no paid API. All data is synthetic (Synthea); no human or patient data is used.

## Quick start (pilot)
```bash
# 1. FHIR server
docker compose -f pilot/docker-compose.yml up -d

# 2. Synthetic patients (fixed seeds)
java -jar synthea-with-dependencies.jar -p 100 -s 20261003 -cs 20261003 -r 20261001 Massachusetts

# 3. Load and verify
python pilot/load_fhir.py <synthea_fhir_dir>
python pilot/verify_fhir_load.py <synthea_fhir_dir>

# 4. Local LLM (CPU) + benchmark + agent episodes
docker run -p 127.0.0.1:8091:8080 -v <models>:/models ghcr.io/ggml-org/llama.cpp:server -m /models/<model>.gguf --jinja -c 16384
python pilot/llm_bench.py <label> <synthea_fhir_dir>
python pilot/agent_episode.py <label> 3

# 5. Formal model
docker run --rm -v "$PWD/formal/tamarin:/work" ubuntu:24.04 bash /work/run_tamarin.sh pilot_mandate_fixed.spthy
```

## License
To be decided before public release (Apache-2.0 planned).
