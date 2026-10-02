"""Pilot: yerel LLM ile FHIR araçları kullanan örnek ajan koşuları.

Ölçülenler:
  - Koşu süresi, LLM çağrı sayısı ve token sayıları.
  - Araç çağrılarının başarısı.
  - Deterministik doğruluk: cevaptaki aktif tanıların HAPI'deki gerçek kayıtlarla eşleşme oranı (LLM-as-judge yok).
Pilot ölçümüdür; asıl deney düzeneği ayrıca kurulacak.

Kullanım: python agent_episode.py <model_etiketi> [n_koşu] [llm_url] [fhir_url]
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import httpx

LABEL = sys.argv[1] if len(sys.argv) > 1 else "test"
N_EPISODES = int(sys.argv[2]) if len(sys.argv) > 2 else 3
LLM = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8091"
FHIR = sys.argv[4] if len(sys.argv) > 4 else "http://127.0.0.1:8090/fhir"
MAX_TURNS = 8
LOGS = Path(__file__).parent / "logs"

fhir = httpx.Client(base_url=FHIR, timeout=60, headers={"Accept": "application/fhir+json"})


_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


def norm(s: str) -> str:
    """Eşleştirmeden önce Unicode farklarını giderir.

    Bazı modeller dar bölünmez boşluk (U+202F) ve bölünmez tire (U+2011) gibi tipografik
    karakterler üretir. Normalizasyon yapılmazsa doğru cevaplar "yanlış" sayılır.
    """
    s = unicodedata.normalize("NFKC", s).translate(_DASHES)
    return " ".join(s.lower().split())


def score_answer(answer: str, conditions: list[str], medications: list[str]) -> dict:
    """Cevapta yer alan gerçek aktif tanı ve ilaçların oranı (normalize edilmiş alt dizgi eşleşmesi).

    Sınırlılık: Yalnız duyarlılığı (recall) ölçer. Yanlış eklemeler ve eşanlamlılar değerlendirilmez.
    """
    a = norm(answer or "")
    ch = [c for c in conditions if c and norm(c) in a]
    mh = [m for m in medications if m and norm(m) in a]
    return {"condition_recall": round(len(ch) / max(1, len(conditions)), 2),
            "medication_recall": round(len(mh) / max(1, len(medications)), 2)}


def _text(cc: dict | None) -> str:
    cc = cc or {}
    return cc.get("text") or ((cc.get("coding") or [{}])[0].get("display") or "")


# ---- FHIR araçları (salt okunur; geniş yetki = pilotta yetkilendirme yok) ----
def find_patient(name: str) -> list[dict]:
    # HAPI'nin "name" parametresi boşluklu tam adı eşleştirmiyor (pilot hatası, 3 Eki).
    # Bu yüzden ad ve soyad ayrı parametrelerle aranır.
    parts = name.split()
    params = {"given": parts[0], "family": parts[-1]} if len(parts) >= 2 else {"name": name}
    b = fhir.get("/Patient", params={**params, "_count": 5}).json()
    out = []
    for e in b.get("entry", []):
        r = e["resource"]
        n = (r.get("name") or [{}])[0]
        out.append({"id": r["id"], "name": " ".join(n.get("given", []) + [n.get("family", "")]),
                    "birthDate": r.get("birthDate"), "gender": r.get("gender")})
    return out


def get_active_conditions(patient_id: str) -> list[dict]:
    b = fhir.get("/Condition", params={"patient": patient_id, "clinical-status": "active", "_count": 50}).json()
    return [{"condition": _text(e["resource"].get("code")), "onset": e["resource"].get("onsetDateTime")}
            for e in b.get("entry", [])]


def get_active_medications(patient_id: str) -> list[dict]:
    b = fhir.get("/MedicationRequest", params={"patient": patient_id, "status": "active", "_count": 50}).json()
    return [{"medication": _text(e["resource"].get("medicationCodeableConcept")),
             "authoredOn": e["resource"].get("authoredOn")} for e in b.get("entry", [])]


TOOLS_IMPL = {"find_patient": find_patient, "get_active_conditions": get_active_conditions,
              "get_active_medications": get_active_medications}
TOOLS_SPEC = [
    {"type": "function", "function": {"name": "find_patient", "description": "Search patients by name. Returns id, name, birthDate, gender.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_active_conditions", "description": "List active conditions for a patient id.",
     "parameters": {"type": "object", "properties": {"patient_id": {"type": "string"}}, "required": ["patient_id"]}}},
    {"type": "function", "function": {"name": "get_active_medications", "description": "List active medication requests for a patient id.",
     "parameters": {"type": "object", "properties": {"patient_id": {"type": "string"}}, "required": ["patient_id"]}}},
]


def pick_patients(n: int) -> list[dict]:
    """En az 3 aktif tanısı ve en az 1 aktif ilacı olan hastaları seçer (deterministik sıra)."""
    b = fhir.get("/Patient", params={"_count": 200, "_sort": "_id"}).json()
    chosen = []
    for e in b.get("entry", []):
        r = e["resource"]
        if r.get("deceasedDateTime"):
            continue
        conds = get_active_conditions(r["id"])
        meds = get_active_medications(r["id"])
        if len(conds) >= 3 and len(meds) >= 1:
            n0 = (r.get("name") or [{}])[0]
            chosen.append({"id": r["id"], "given": n0.get("given", [""])[0], "family": n0.get("family", ""),
                           "conditions": sorted({c["condition"] for c in conds}),
                           "medications": sorted({m["medication"] for m in meds})})
        if len(chosen) >= n:
            break
    return chosen


def run_episode(client: httpx.Client, pt: dict) -> dict:
    task = (f"Prepare a brief rehabilitation referral summary for the patient named {pt['given']} {pt['family']}. "
            "List ALL of their active conditions and active medications exactly as recorded. "
            "Use the tools to retrieve data; do not invent anything.")
    messages = [{"role": "system", "content": "You are a clinical assistant with access to FHIR tools."},
                {"role": "user", "content": task}]
    stats = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "tool_errors": 0}
    t0 = time.perf_counter()
    final = None
    for _ in range(MAX_TURNS):
        payload = {"messages": messages, "tools": TOOLS_SPEC, "tool_choice": "auto",
                   "temperature": 0, "max_tokens": 1024,
                   "chat_template_kwargs": {"reasoning_effort": "low"}}
        r = client.post(f"{LLM}/v1/chat/completions", json=payload, timeout=3600)
        r.raise_for_status()
        d = r.json()
        stats["llm_calls"] += 1
        stats["prompt_tokens"] += d.get("usage", {}).get("prompt_tokens", 0)
        stats["completion_tokens"] += d.get("usage", {}).get("completion_tokens", 0)
        msg = d["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls", "reasoning_content")})
        if not calls:
            final = msg.get("content") or ""
            break
        for c in calls:
            stats["tool_calls"] += 1
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                result = TOOLS_IMPL[c["function"]["name"]](**args)
            except Exception as ex:  # araç hatası modele geri bildirilir
                stats["tool_errors"] += 1
                result = {"error": str(ex)}
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": json.dumps(result)})
    wall = time.perf_counter() - t0
    return {"patient": f"{pt['given']} {pt['family']}", "patient_id": pt["id"],
            "wall_s": round(wall, 1), **stats, "finished": final is not None,
            **score_answer(final, pt["conditions"], pt["medications"]),
            "n_true_conditions": len(pt["conditions"]), "n_true_medications": len(pt["medications"]),
            "true_conditions": pt["conditions"], "true_medications": pt["medications"],
            "transcript": messages}


def main() -> None:
    patients = pick_patients(N_EPISODES)
    results = []
    with httpx.Client() as client:
        for pt in patients:
            res = run_episode(client, pt)
            results.append(res)
            print(json.dumps({k: v for k, v in res.items() if k != "transcript"}), flush=True)
    (LOGS / f"episodes_{LABEL}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
