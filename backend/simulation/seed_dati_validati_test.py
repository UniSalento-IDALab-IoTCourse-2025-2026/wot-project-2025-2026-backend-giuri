"""
backend/simulation/seed_dati_validati_test.py

Script di SOLO TEST: popola la collection `annotations` su MongoDB con
documenti già validati dal medico (esito_medico valorizzato), in modo
da poter testare retrain_scheduler.py / RetrainService senza dover
prima passare manualmente per tutto il flusso live (simulate_stream.py
→ mqtt_subscriber.py → validazione da dashboard) decine di volte.

Genera:
- metà documenti con rr_intervals "regolari" (RR ~0.78-0.82s) etichettati
  vero_positivo (simula anomalie confermate dal medico)
- metà documenti con rr_intervals "caotici" (RR irregolari, stile
  fibrillazione atriale) etichettati falso_allarme (simula anomalie
  poi giudicate non cliniche dal medico)

Le due classi sono volutamente "invertite" rispetto a cosa ci si
aspetterebbe nella realtà clinica: lo scopo qui non è realismo clinico
ma solo avere due classi linearmente separabili nelle feature, per
verificare rapidamente che la pipeline di retrain (estrazione feature
→ fit → salvataggio atomico → hot-reload) funzioni end-to-end.

Uso:
    cd backend
    python simulation/seed_dati_validati_test.py --n 20
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from db.mongo_client import get_db

PAZIENTE_ID_TEST = "TESTSEED1"


def genera_rr_regolare(n: int = 10) -> list:
    return [round(random.uniform(0.78, 0.82), 3) for _ in range(n)]


def genera_rr_caotico(n: int = 10) -> list:
    pool = [0.38, 0.41, 0.44, 0.49, 0.52, 1.05, 1.18, 1.32, 1.40, 0.47]
    return [random.choice(pool) for _ in range(n)]


def costruisci_documento(rr: list, esito: str, offset_minuti: int) -> dict:
    adesso = datetime.now(timezone.utc) - timedelta(minutes=offset_minuti)
    return {
        "paziente_id": PAZIENTE_ID_TEST,
        "timestamp": adesso,
        "ecg_label": "anomalo",
        "ecg_score": round(random.uniform(0.55, 0.95), 4),
        "rr_intervals": rr,
        "ecg_raw_snapshot": None,
        "postura_label": "seduto",
        "postura_score": 0.9,
        "temperatura_label": "normale",
        "temperatura_valore": 36.7,
        "tipo_annotazione": "automatica",
        "esito_medico": esito,
        "note_medico": "[seed di test] generato da seed_dati_validati_test.py",
        "validato_at": adesso,
        "ecg_window": None,
        "ecg_window_sample_rate": 250,
        "ecg_window_anomalia_index": None,
        "ecg_window_pronta": False
    }


def main():
    parser = argparse.ArgumentParser(
        description="Popola MongoDB con annotazioni validate fittizie per testare il retrain"
    )
    parser.add_argument(
        "--n", type=int, default=20,
        help="Numero totale di documenti da generare (default: 20, "
             "diviso a metà tra le due classi)"
    )
    parser.add_argument(
        "--pulisci", action="store_true",
        help="Rimuove prima eventuali documenti di test precedenti "
             f"(paziente_id={PAZIENTE_ID_TEST}) prima di generarne di nuovi"
    )
    args = parser.parse_args()

    db = get_db()
    collection = db["annotations"]

    if args.pulisci:
        risultato = collection.delete_many({"paziente_id": PAZIENTE_ID_TEST})
        print(f"Rimossi {risultato.deleted_count} documenti di test precedenti.")

    meta = args.n // 2
    documenti = []

    for i in range(meta):
        documenti.append(costruisci_documento(
            genera_rr_regolare(), "vero_positivo", offset_minuti=i
        ))
    for i in range(args.n - meta):
        documenti.append(costruisci_documento(
            genera_rr_caotico(), "falso_allarme", offset_minuti=meta + i
        ))

    risultato = collection.insert_many(documenti)
    print(f"Inseriti {len(risultato.inserted_ids)} documenti validati di test "
          f"(paziente_id={PAZIENTE_ID_TEST}): "
          f"{meta} vero_positivo, {args.n - meta} falso_allarme.")
    print("\nOra puoi testare il retrain con:")
    print("    python retrain_scheduler.py --now")


if __name__ == "__main__":
    main()