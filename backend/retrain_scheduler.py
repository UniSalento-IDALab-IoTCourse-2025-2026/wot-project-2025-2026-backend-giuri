"""
backend/retrain_scheduler.py

Processo standalone separato da mqtt_subscriber.py e fastapi_server.py.
Esegue il ri-addestramento del modello ECG ogni notte ad un orario fisso,
usando le annotazioni validate dal medico accumulate su MongoDB.

Va avviato come processo indipendente (es. `python retrain_scheduler.py`,
o come servizio dedicato in docker-compose / systemd / supervisord).
Non condivide memoria con gli altri processi: la propagazione del nuovo
modello agli ECGClassifier già in esecuzione avviene tramite il
meccanismo di hot-reload basato su mtime del file .pkl (vedi
classifiers/ecg_classifier.py), non tramite comunicazione diretta.

Avvio:
    cd backend
    python retrain_scheduler.py

Variabili d'ambiente (opzionali, .env):
    RETRAIN_ORA   - ora del giorno per il retrain (default: 3)
    RETRAIN_MINUTO - minuto (default: 0)
"""
import argparse
import os
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from db.mongo_client import get_db
from repositories.annotation_repository import AnnotationRepository
from services.retrain_service import RetrainService

load_dotenv()

ECG_MODEL_PATH = "ai/trained/ecg_model.pkl"

RETRAIN_ORA = int(os.getenv("RETRAIN_ORA", 3))
RETRAIN_MINUTO = int(os.getenv("RETRAIN_MINUTO", 0))


def esegui_retrain():
    """
    Job schedulato: apre una connessione al DB, esegue il retrain e
    logga l'esito. Ogni esecuzione ricostruisce repo/service da zero
    invece di tenerli come stato globale: lo scheduler resta in vita
    per giorni/settimane e ricreare oggetti leggeri ad ogni job evita
    di tenere aperta inutilmente una connessione MongoDB per ore.
    """
    adesso = datetime.now(timezone.utc).isoformat()
    print(f"\n[{adesso}] Avvio job di ri-addestramento ECG...")

    try:
        db = get_db()
        repo = AnnotationRepository(db)
        service = RetrainService(repo, model_path=ECG_MODEL_PATH)

        successo = service.ritrain()

        if successo:
            print(f"[{adesso}] Ri-addestramento completato con successo.")
        else:
            print(f"[{adesso}] Ri-addestramento saltato (dati insufficienti).")

    except Exception as e:
        # Un job fallito non deve far crashare lo scheduler: il
        # prossimo tentativo è comunque la notte successiva.
        print(f"[{adesso}] Errore durante il ri-addestramento: {e}")


def shutdown(signum, frame):
    print("\nArresto retrain_scheduler in corso...")
    scheduler.shutdown(wait=False)
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CardioSense — Scheduler retrain ECG"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Esegue il retrain immediatamente una sola volta e termina "
             "(per test manuali, senza aspettare l'orario pianificato)"
    )
    args = parser.parse_args()

    if args.now:
        print("Modalità test (--now): eseguo il retrain immediatamente...")
        esegui_retrain()
        sys.exit(0)

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        esegui_retrain,
        trigger=CronTrigger(hour=RETRAIN_ORA, minute=RETRAIN_MINUTO),
        id="retrain_ecg_notturno",
        name="Ri-addestramento notturno modello ECG",
        misfire_grace_time=3600,  # tollera fino a 1h di ritardo (es. macchina spenta)
        coalesce=True             # se più esecuzioni sono "in ritardo", ne esegue una sola
    )

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("CardioSense Retrain Scheduler avviato.")
    print(f"Prossimo retrain pianificato ogni giorno alle {RETRAIN_ORA:02d}:{RETRAIN_MINUTO:02d} UTC.")
    print("Premi CTRL+C per fermare.\n")

    scheduler.start()