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
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Root del progetto, calcolata dalla posizione di QUESTO file
# (backend/db/mqtt_tls.py -> backend/ -> root), non dalla cwd del
# processo che lo importa.
#
# Necessario perché i vari entry point vengono avviati da directory
# diverse per convenzione del progetto:
#   - mqtt_subscriber.py       -> lanciato dalla root
#   - fastapi_server.py        -> lanciato da backend/
#   - simulate_stream.py       -> lanciato da backend/simulation/
# Un path relativo tipo "mosquitto/certs/ca.crt" risolverebbe in modo
# diverso (e nella maggior parte dei casi errato) a seconda di dove
# viene lanciato il comando. Ancorandolo alla root risolta da __file__
# il comportamento è identico ovunque lo script venga eseguito.
# ------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _risolvi_percorso(path_str: str) -> str:
    """
    Se il path da .env è già assoluto lo lascia invariato (permette a
    chi vuole massima esplicitezza di configurare un path assoluto
    nel proprio .env). Altrimenti lo risolve rispetto alla root del
    progetto invece che alla cwd corrente.
    """
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str((_PROJECT_ROOT / p).resolve())


CA_CERT_PATH = _risolvi_percorso(os.getenv("MQTT_CA_CERT", "mosquitto/certs/ca.crt"))
MQTT_PORT_TLS = int(os.getenv("MQTT_PORT", 8883))
MQTT_TLS_ENABLED = os.getenv("MQTT_TLS_ENABLED", "true").lower() == "true"


def configura_tls(client) -> None:
    """
    Abilita TLS su un client paho-mqtt usando la CA locale (mkcert).

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

    if not os.path.exists(CA_CERT_PATH):
        raise FileNotFoundError(
            f"Certificato CA non trovato in: {CA_CERT_PATH}\n"
            f"Verifica che 'mosquitto/certs/ca.crt' esista nella root del "
            f"progetto, oppure imposta MQTT_CA_CERT nel .env con un path "
            f"assoluto."
        )

    client.tls_set(
        ca_certs=CA_CERT_PATH,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )


def get_mqtt_port(default_plain: int = 1883) -> int:
    """Ritorna la porta MQTT corretta in base allo stato di MQTT_TLS_ENABLED."""
    if MQTT_TLS_ENABLED:
        return int(os.getenv("MQTT_PORT", MQTT_PORT_TLS))
    return int(os.getenv("MQTT_PORT", default_plain))