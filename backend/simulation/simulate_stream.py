import json
import time
import random
import numpy as np
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOPIC_DATI = "cardiosense/dati"
PAZIENTE_ID = "A3KX9BPQ"  # codice paziente di test

# Frequenza di pubblicazione messaggi (secondi)
INTERVALLO_PUBBLICAZIONE = 1.0

# ============================================================
# GENERATORI DI SEGNALI SINTETICI
# ============================================================

def genera_ecg_normale(n_campioni: int = 10) -> list:
    """
    Genera campioni ECG sintetici che simulano un ritmo sinusale normale.
    I picchi R sono regolari con leggera variabilità (HRV fisiologica).
    """
    baseline = 1024
    campioni = []

    for i in range(n_campioni):
        # Simula un QRS con picco ogni ~250 campioni (1 Hz a 250 Hz)
        fase = (i % 25) / 25.0
        if 0.4 < fase < 0.6:
            # Picco R
            valore = baseline + int(500 * np.sin(np.pi * (fase - 0.4) / 0.2))
        else:
            # Baseline con rumore fisiologico
            valore = baseline + random.randint(-20, 20)
        campioni.append(valore)

    return campioni


def genera_ecg_anomalo(n_campioni: int = 10) -> list:
    """
    Genera campioni ECG sintetici che simulano un ritmo irregolare
    (es. aritmia) con picchi casuali e variabilità elevata.
    """
    baseline = 1024
    campioni = []

    for i in range(n_campioni):
        # Picchi irregolari e rumore elevato
        if random.random() < 0.3:
            valore = baseline + random.randint(300, 700)
        else:
            valore = baseline + random.randint(-100, 100)
        campioni.append(valore)

    return campioni


def genera_accelerometro_normale() -> dict:
    """
    Simula accelerometro di una persona ferma o in leggero movimento.
    La componente z è dominante (gravità ~1g).
    """
    return {
        "acc_x": round(random.uniform(-0.1, 0.1), 3),
        "acc_y": round(random.uniform(-0.1, 0.1), 3),
        "acc_z": round(random.uniform(0.95, 1.05), 3)
    }


def genera_accelerometro_movimento() -> dict:
    """
    Simula accelerometro durante movimento (camminata).
    """
    return {
        "acc_x": round(random.uniform(-0.5, 0.5), 3),
        "acc_y": round(random.uniform(-0.5, 0.5), 3),
        "acc_z": round(random.uniform(0.7, 1.3), 3)
    }


def genera_temperatura_normale() -> float:
    """
    Simula temperatura corporea normale.
    """
    return round(random.uniform(36.2, 37.2), 1)


def genera_temperatura_febbre() -> float:
    """
    Simula temperatura febbrile.
    """
    return round(random.uniform(37.5, 38.5), 1)


# ============================================================
# SCENARI DI TEST
# ============================================================

SCENARI = {
    "normale": {
        "descrizione": "Paziente a riposo, parametri nella norma",
        "ecg_fn": genera_ecg_normale,
        "acc_fn": genera_accelerometro_normale,
        "temp_fn": genera_temperatura_normale
    },
    "anomalia_ecg": {
        "descrizione": "Aritmia rilevata, altri parametri normali",
        "ecg_fn": genera_ecg_anomalo,
        "acc_fn": genera_accelerometro_normale,
        "temp_fn": genera_temperatura_normale
    },
    "febbre": {
        "descrizione": "Temperatura elevata, ECG normale",
        "ecg_fn": genera_ecg_normale,
        "acc_fn": genera_accelerometro_normale,
        "temp_fn": genera_temperatura_febbre
    },
    "movimento": {
        "descrizione": "Paziente in movimento, ECG normale",
        "ecg_fn": genera_ecg_normale,
        "acc_fn": genera_accelerometro_movimento,
        "temp_fn": genera_temperatura_normale
    }
}


# ============================================================
# PUBBLICAZIONE MQTT
# ============================================================

def costruisci_payload(scenario: str) -> dict:
    """
    Costruisce il payload MQTT per lo scenario scelto.
    """
    s = SCENARI[scenario]
    acc = s["acc_fn"]()

    return {
        "paziente_id": PAZIENTE_ID,
        "ecg_raw": s["ecg_fn"](),
        "acc_x": acc["acc_x"],
        "acc_y": acc["acc_y"],
        "acc_z": acc["acc_z"],
        "temperatura": s["temp_fn"]()
    }


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connesso al broker MQTT")
    else:
        print(f"Connessione fallita — codice: {reason_code}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CardioSense — Simulatore streaming dati paziente"
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARI.keys()),
        default="normale",
        help="Scenario da simulare (default: normale)"
    )
    parser.add_argument(
        "--durata",
        type=int,
        default=60,
        help="Durata della simulazione in secondi (default: 60)"
    )
    parser.add_argument(
        "--intervallo",
        type=float,
        default=INTERVALLO_PUBBLICAZIONE,
        help="Intervallo tra messaggi in secondi (default: 1.0)"
    )
    args = parser.parse_args()

    print(f"Scenario: {args.scenario} — {SCENARI[args.scenario]['descrizione']}")
    print(f"Durata: {args.durata}s, Intervallo: {args.intervallo}s")
    print(f"Paziente ID: {PAZIENTE_ID}")
    print("-" * 50)

    client = mqtt.Client(
        client_id="cardiosense_simulator",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.on_connect = on_connect
    client.connect(
        os.getenv("MQTT_BROKER", "localhost"),
        int(os.getenv("MQTT_PORT", 1883))
    )
    client.loop_start()

    inizio = time.time()
    messaggi_inviati = 0

    try:
        while time.time() - inizio < args.durata:
            payload = costruisci_payload(args.scenario)
            client.publish(
                TOPIC_DATI,
                json.dumps(payload),
                qos=1
            )
            messaggi_inviati += 1
            print(f"[{messaggi_inviati}] Pubblicato — "
                  f"ECG samples: {len(payload['ecg_raw'])}, "
                  f"Temp: {payload['temperatura']}°C, "
                  f"Acc: ({payload['acc_x']}, {payload['acc_y']}, {payload['acc_z']})")
            time.sleep(args.intervallo)

    except KeyboardInterrupt:
        print("\nSimulazione interrotta.")
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"\nSimulazione completata — {messaggi_inviati} messaggi inviati.")