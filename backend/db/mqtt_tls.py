# backend/db/mqtt_tls.py
"""
Utility condivisa per abilitare TLS sui client paho-mqtt del progetto.
Centralizzata qui per evitare di duplicare la configurazione SSL in
ogni modulo che apre una connessione MQTT (mqtt_subscriber.py,
notification_service.py, simulate_stream.py, mqtt_bridge.py,
patient_anomalies.py).
"""
import os
import ssl
from dotenv import load_dotenv

load_dotenv()

CA_CERT_PATH = os.getenv("MQTT_CA_CERT", "mosquitto/certs/ca.crt")
MQTT_PORT_TLS = int(os.getenv("MQTT_PORT", 8883))
MQTT_TLS_ENABLED = os.getenv("MQTT_TLS_ENABLED", "true").lower() == "true"


def configura_tls(client) -> None:
    """
    Abilita TLS su un client paho-mqtt usando la CA self-signed locale.

    Il certificato server ha CN=localhost: la verifica dell'hostname
    funziona finché ci si connette a "localhost". Se il broker gira su
    un host diverso, va passato un certificato con CN coerente, oppure
    (solo per debug, MAI in produzione) disabilitata la verifica con
    client.tls_insecure_set(True) dopo questa chiamata.

    Se MQTT_TLS_ENABLED=false (.env), questa funzione non fa nulla,
    permettendo un fallback rapido al listener 1883 in chiaro durante
    lo sviluppo/debug locale.
    """
    if not MQTT_TLS_ENABLED:
        return

    client.tls_set(
        ca_certs=CA_CERT_PATH,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )


def get_mqtt_port(default_plain: int = 1883) -> int:
    """Ritorna la porta MQTT corretta in base allo stato di MQTT_TLS_ENABLED."""
    if MQTT_TLS_ENABLED:
        return int(os.getenv("MQTT_PORT", MQTT_PORT_TLS))
    return int(os.getenv("MQTT_PORT", default_plain))