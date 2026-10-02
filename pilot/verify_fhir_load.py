"""Yükleme doğrulaması: Synthea dosyalarındaki kaynak sayılarını
HAPI'de gerçekten kalıcılaşan sayılarla (_summary=count) karşılaştırır.

Kullanım: python verify_fhir_load.py <synthea_fhir_klasoru> [base_url]
Çıkış kodu: tüm türler eşleşirse 0, değilse 1.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import httpx

FOLDER = Path(sys.argv[1])
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8090/fhir"


def expected_counts() -> Counter:
    c, seen = Counter(), set()
    for f in sorted(FOLDER.glob("*.json")):
        for e in json.loads(f.read_text(encoding="utf-8")).get("entry", []):
            r = e.get("resource", {})
            req = e.get("request", {})
            # Koşullu oluşturma (ifNoneExist) aynı Organization/Practitioner'ı tekrar yaratmaz
            key = (r.get("resourceType"), req.get("ifNoneExist") or e.get("fullUrl"))
            if key in seen:
                continue
            seen.add(key)
            c[r.get("resourceType")] += 1
    return c


def main() -> None:
    exp = expected_counts()
    rows, ok = [], True
    with httpx.Client(base_url=BASE, timeout=120) as cl:
        for rt in sorted(exp):
            got = cl.get(f"/{rt}", params={"_summary": "count"}).json().get("total")
            match = got == exp[rt]
            ok &= match
            rows.append({"type": rt, "expected": exp[rt], "in_hapi": got, "match": match})
    print(json.dumps({"all_match": ok, "types": len(rows),
                      "expected_total": sum(exp.values()),
                      "hapi_total": sum((r["in_hapi"] or 0) for r in rows),
                      "mismatches": [r for r in rows if not r["match"]]}, indent=2))
    Path(__file__).parent.joinpath("logs", "verify_fhir_load.json").write_text(json.dumps(rows, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
