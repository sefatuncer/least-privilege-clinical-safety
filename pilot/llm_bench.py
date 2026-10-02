"""llama-server (OpenAI uyumlu API) için hız ölçümü: prompt işleme ve üretim hızı (token/s).

Gerçekçi bir girdi kullanır: bir Synthea hastasının FHIR kaynaklarından kesilmiş metin.
Uzunluk KARAKTER cinsinden hedeflenir; gerçek token sayısı modele göre değişir ve sunucunun
usage/timings alanlarından raporlanır (ör. 12.000 karakter = Gemma'da 6.313, gpt-oss'ta 4.818 token).
Kullanım: python llm_bench.py <model_etiketi> <synthea_fhir_klasoru> [base_url] [hedef_prompt_karakteri]
"""
import json
import sys
import time
from pathlib import Path

import httpx

LABEL = sys.argv[1]
FHIR_DIR = Path(sys.argv[2])
BASE = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8091"
TARGET_CHARS = int(sys.argv[4]) if len(sys.argv) > 4 else 12000  # karakter (token değil)


def build_context() -> str:
    patient_file = next(f for f in sorted(FHIR_DIR.glob("*.json"))
                        if not f.name.startswith(("hospital", "practitioner")))
    bundle = json.loads(patient_file.read_text(encoding="utf-8"))
    lines = []
    for e in bundle.get("entry", []):
        r = e.get("resource", {})
        rt = r.get("resourceType")
        if rt in ("Condition", "MedicationRequest", "Observation", "Encounter"):
            if rt == "Encounter":
                code = (r.get("type") or [{}])[0]
            else:
                code = r.get("code") or r.get("medicationCodeableConcept") or {}
            text = code.get("text")
            when = r.get("onsetDateTime") or r.get("authoredOn") or r.get("effectiveDateTime") or (r.get("period") or {}).get("start")
            val = r.get("valueQuantity", {})
            lines.append(f"{rt} | {text} | {when} | {val.get('value', '')} {val.get('unit', '')}".strip())
        if sum(len(x) for x in lines) > TARGET_CHARS:
            break
    return "\n".join(lines)


def ask(client: httpx.Client, context: str, suffix: str = "") -> dict:
    payload = {
        "messages": [
            {"role": "system", "content": "You are a clinical documentation assistant. Be concise."},
            {"role": "user", "content": f"Patient record excerpt:\n{context}\n\nSummarize the active problems in 5 bullet points.{suffix}"},
        ],
        "max_tokens": 256,
        "temperature": 0,
        "chat_template_kwargs": {"reasoning_effort": "low"},  # yalnız gpt-oss kullanır; diğerleri yok sayar
    }
    t0 = time.perf_counter()
    r = client.post(f"{BASE}/v1/chat/completions", json=payload, timeout=1800)
    r.raise_for_status()
    d = r.json()
    d["_wall_s"] = time.perf_counter() - t0
    return d


def main() -> None:
    ctx = build_context()
    out = {"model": LABEL, "context_chars": len(ctx), "runs": []}
    with httpx.Client() as client:
        for i, suffix in enumerate(["", "", " (rerun A)", " (rerun B)"]):
            # 1. koşu soğuk; 2. koşu aynı prompt (önbellek); 3–4 küçük ekli varyasyon
            d = ask(client, ctx, suffix)
            t = d.get("timings", {})
            u = d.get("usage", {})
            out["runs"].append({
                "run": i, "wall_s": round(d["_wall_s"], 1),
                "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                "prompt_n_processed": t.get("prompt_n"), "prompt_tps": round(t.get("prompt_per_second", 0), 1),
                "gen_tps": round(t.get("predicted_per_second", 0), 1),
            })
            print(json.dumps(out["runs"][-1]), flush=True)
    Path(__file__).parent.joinpath("logs", f"bench_{LABEL}.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
