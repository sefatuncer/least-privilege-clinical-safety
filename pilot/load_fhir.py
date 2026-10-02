"""Synthea FHIR R4 transaction bundle'larını HAPI FHIR sunucusuna yükler ve süreyi ölçer.

Yükleme sırası:
  1. hospitalInformation* ve practitionerInformation*: hasta bundle'ları bunlara koşullu referans verir.
  2. Hasta bundle'ları (paralel).

Kullanım: python load_fhir.py <fhir_klasoru> [base_url] [paralellik]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8090/fhir"
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
HEADERS = {"Content-Type": "application/fhir+json"}


def post_bundle(client: httpx.Client, path: Path) -> tuple[str, int, float, int]:
    body = path.read_bytes()
    t0 = time.perf_counter()
    r = client.post(BASE, content=body, headers=HEADERS, timeout=600)
    n_entries = len(json.loads(body).get("entry", []))
    return path.name, r.status_code, time.perf_counter() - t0, n_entries


def main() -> None:
    folder = Path(sys.argv[1])
    files = sorted(folder.glob("*.json"))
    infra = [f for f in files if f.name.startswith(("hospitalInformation", "practitionerInformation"))]
    patients = [f for f in files if f not in infra]
    results = []
    t_start = time.perf_counter()
    with httpx.Client() as client:
        for f in infra:  # sıralı
            results.append(post_bundle(client, f))
        t_infra = time.perf_counter() - t_start
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(post_bundle, client, f) for f in patients]
            for fut in as_completed(futs):
                results.append(fut.result())
    total = time.perf_counter() - t_start
    failed = [r for r in results if r[1] >= 300]
    entries = sum(r[3] for r in results)
    summary = {
        "bundles": len(results),
        "patients_bundles": len(patients),
        "entries_total": entries,
        "failed": len(failed),
        "failed_examples": failed[:5],
        "infra_seconds": round(t_infra, 1),
        "total_seconds": round(total, 1),
        "entries_per_second": round(entries / total, 1),
        "workers": WORKERS,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
