import json
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv
from models.annotation import Annotation
from db.mqtt_tls import configura_tls, get_mqtt_port

load_dotenv()


class NotificationService:
    """
    Gestisce l'invio di notifiche via MQTT sia al medico (nuove anomalie)
    sia al paziente (esito della validazione medica di un episodio).
    Due topic distinti perché i consumer si aspettano forme di payload
    diverse: la dashboard medico e patient_anomalies.py leggerebbero
    campi (es. ecg_score) che non hanno senso per un evento di validazione.
    """

    TOPIC_ALLARMI = "cardiosense/allarmi"
    TOPIC_VALIDAZIONI = "cardiosense/validazioni"

    def __init__(self):
        self.client = mqtt.Client(
            client_id="notification_service",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        configura_tls(self.client)
        self.client.connect(
            os.getenv("MQTT_BROKER", "localhost"),
            get_mqtt_port()
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

    def notifica_validazione(
        self,
        paziente_id: str,
        esito: str,
        note: str | None,
        numero_letture: int = 1
    ) -> None:
        """
        Pubblica l'esito della validazione medica di un episodio (singola
        lettura o gruppo raggruppato), così l'app paziente può notificarlo
        in tempo reale senza dover fare polling sullo storico.
        """
        payload = {
            "tipo": "validazione_medico",
            "paziente_id": paziente_id,
            "esito_medico": esito,
            "note_medico": note,
            "numero_letture": numero_letture
        }

        self.client.publish(
            self.TOPIC_VALIDAZIONI,
            json.dumps(payload),
            qos=1
        )