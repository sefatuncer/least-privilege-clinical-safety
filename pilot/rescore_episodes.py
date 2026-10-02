"""Kayıtlı ajan koşularını modeli yeniden çalıştırmadan yeniden puanlar.

Gerçek aktif tanı ve ilaçlar FHIR sunucusundan yeniden alınır; puanlama agent_episode.score_answer
(Unicode-normalize eşleşme) ile yapılır.

Kullanım: python rescore_episodes.py <episodes_json> [fhir_url]
"""
import json
import sys
from pathlib import Path

import agent_episode as ae


def final_answer(transcript: list[dict]) -> str:
    finals = [m for m in transcript if m.get("role") == "assistant" and not m.get("tool_calls")]
    return (finals[-1].get("content") or "") if finals else ""


def main() -> None:
    path = Path(sys.argv[1])
    episodes = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for ep in episodes:
        hits = ae.find_patient(ep["patient"])
        if len(hits) != 1:
            raise SystemExit(f"Hasta eşleşmesi tekil değil: {ep['patient']} -> {len(hits)}")
        pid = hits[0]["id"]
        conds = sorted({c["condition"] for c in ae.get_active_conditions(pid)})
        meds = sorted({m["medication"] for m in ae.get_active_medications(pid)})
        row = {"patient": ep["patient"], "patient_id": pid,
               "old": {k: ep.get(k) for k in ("condition_recall", "medication_recall")},
               "new": ae.score_answer(final_answer(ep["transcript"]), conds, meds)}
        out.append(row)
        print(json.dumps(row, ensure_ascii=False))
    path.with_name(path.stem + "_rescored.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
