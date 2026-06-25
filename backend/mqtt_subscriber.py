import json
import signal
import sys
import os
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from db.mongo_client import get_db
from classifiers.ecg_classifier import ECGClassifier
from classifiers.postura_classifier import PosturaClassifier
from classifiers.temperatura_classifier import TemperaturaClassifier
from repositories.annotation_repository import AnnotationRepository
from services.annotation_service import AnnotationService
from services.notification_service import NotificationService

load_dotenv()

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOPIC_DATI = "cardiosense/dati"
TOPIC_ALLARMI = "cardiosense/allarmi"

ECG_MODEL_PATH = "backend/ai/trained/ecg_model.pkl"
POSTURA_MODEL_PATH = "backend/ai/trained/postura_model.pkl"

# ============================================================
# INIZIALIZZAZIONE COMPONENTI
# ============================================================

# Database
db = get_db()

# Classificatori
ecg_classifier = ECGClassifier(ECG_MODEL_PATH)
postura_classifier = PosturaClassifier(POSTURA_MODEL_PATH)
temperatura_classifier = TemperaturaClassifier()

# Repository
annotation_repo = AnnotationRepository(db)

# Services
annotation_service = AnnotationService(
    annotation_repo=annotation_repo,
    ecg_classifier=ecg_classifier,
    postura_classifier=postura_classifier,
    temperatura_classifier=temperatura_classifier
)
notification_service = NotificationService()

# ============================================================
# CALLBACKS MQTT
# ============================================================

def on_connect(client, userdata, flags, reason_code, properties):
    """
    Callback chiamata quando il client si connette al broker.
    Si sottoscrive al topic dati.
    """
    if reason_code == 0:
        print(f"Connesso al broker MQTT")
        client.subscribe(TOPIC_DATI, qos=1)
        print(f"Sottoscritto a: {TOPIC_DATI}")
    else:
        print(f"Connessione fallita — codice: {reason_code}")


def on_message(client, userdata, message):
    """
    Callback chiamata ogni volta che arriva un messaggio
    sul topic dati. Elabora il payload e salva su MongoDB.
    """
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        print(f"Messaggio ricevuto per paziente: {payload.get('paziente_id')}")

        # Classifica e salva
        annotation, is_anomalia = annotation_service.processa_lettura(payload)

        print(f"  ECG: {annotation.ecg_label} (score: {annotation.ecg_score})")
        print(f"  Postura: {annotation.postura_label}")
        print(f"  Temperatura: {annotation.temperatura_label} "
              f"({annotation.temperatura_valore}°C)")

        # Se anomalia → notifica medico
        if is_anomalia:
            print(f"  ⚠ Anomalia rilevata — invio notifica al medico")
            notification_service.notifica_anomalia(annotation)

    except json.JSONDecodeError as e:
        print(f"Errore parsing JSON: {e}")
    except Exception as e:
        print(f"Errore elaborazione messaggio: {e}")


def on_disconnect(client, userdata, flags, reason_code, properties):
    """
    Callback chiamata quando il client si disconnette.
    """
    print(f"Disconnesso dal broker MQTT — codice: {reason_code}")


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================

def shutdown(signum, frame):
    """
    Gestisce CTRL+C e SIGTERM in modo pulito.
    """
    print("\nShutdown in corso...")
    client.loop_stop()
    client.disconnect()
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    client = mqtt.Client(
        client_id="cardiosense_subscriber",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    print("Avvio CardioSense MQTT Subscriber...")
    client.connect(
        os.getenv("MQTT_BROKER", "localhost"),
        int(os.getenv("MQTT_PORT", 1883)),
        keepalive=60
    )

    # Loop bloccante — resta in ascolto finché non viene fermato
    client.loop_forever()