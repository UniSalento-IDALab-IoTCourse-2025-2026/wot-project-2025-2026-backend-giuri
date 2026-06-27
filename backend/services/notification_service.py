import json
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv
from models.annotation import Annotation

load_dotenv()


class NotificationService:
    """
    Gestisce l'invio di notifiche al medico
    pubblicando su un topic MQTT dedicato agli allarmi.
    Il broker consegna il messaggio alla dashboard
    che lo trasforma in Web Push Notification.
    """

    TOPIC_ALLARMI = "cardiosense/allarmi"

    def __init__(self):
        self.client = mqtt.Client(
            client_id="notification_service",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self.client.connect(
            os.getenv("MQTT_BROKER", "localhost"),
            int(os.getenv("MQTT_PORT", 1883))
        )
        # Senza il network loop in background, connect() apre solo il socket:
        # publish() accoderebbe i messaggi senza mai scriverli realmente.
        self.client.loop_start()

    def notifica_anomalia(self, annotation: Annotation) -> None:
        """
        Pubblica un messaggio di allarme sul broker MQTT
        quando viene rilevata un'anomalia ECG.
        """
        payload = {
            "tipo": "anomalia_ecg",
            "paziente_id": annotation.paziente_id,
            "timestamp": annotation.timestamp.isoformat(),
            "ecg_label": annotation.ecg_label,
            "ecg_score": annotation.ecg_score,
            "postura_label": annotation.postura_label,
            "temperatura_label": annotation.temperatura_label,
            "temperatura_valore": annotation.temperatura_valore
        }

        self.client.publish(
            self.TOPIC_ALLARMI,
            json.dumps(payload),
            qos=1  # almeno una consegna garantita
        )