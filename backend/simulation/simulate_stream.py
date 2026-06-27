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
PAZIENTE_ID = "OMU9YFPR"  # codice paziente di test

# Frequenza di pubblicazione messaggi (secondi)
INTERVALLO_PUBBLICAZIONE = 1.0

# ============================================================
# GENERATORI DI SEGNALI SINTETICI (Corretti per Data Science)
# ============================================================

def genera_ecg_normale(n_campioni: int = 10) -> list:
    """
    Genera intervalli R-R stabili (intorno a 0.8 secondi).
    Bassa variabilità = Ritmo normale.
    """
    return [round(random.uniform(0.78, 0.82), 2) for _ in range(n_campioni)]


def genera_ecg_anomalo(n_campioni: int = 10) -> list:
    """
    Genera intervalli R-R caotici e instabili.
    Forte variabilità (battiti accelerati alternati a pause lunghe) = Aritmia.
    """
    opzioni_aritmia = [0.42, 0.45, 1.35, 0.49, 1.41, 0.52, 1.15, 0.41, 1.38, 0.44]
    return [random.choice(opzioni_aritmia) for _ in range(n_campioni)]


def genera_accelerometro_normale() -> dict:
    return {
        "acc_x": round(random.uniform(-0.05, 0.05), 3),
        "acc_y": round(random.uniform(-0.05, 0.05), 3),
        "acc_z": round(random.uniform(0.98, 1.02), 3)
    }


def genera_accelerometro_movimento() -> dict:
    return {
        "acc_x": round(random.uniform(-0.6, 0.6), 3),
        "acc_y": round(random.uniform(-0.6, 0.6), 3),
        "acc_z": round(random.uniform(0.5, 1.5), 3)
    }


def genera_temperatura_normale() -> float:
    return round(random.uniform(36.4, 36.9), 1)


def genera_temperatura_febbre() -> float:
    # Portiamo la febbre a un valore indubitabilmente alto (39.2°C)
    return round(random.uniform(38.8, 39.5), 1)


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
    Costruisce il payload MQTT includendo la chiave rr_intervals attesa dall'IA.
    """
    s = SCENARI[scenario]
    acc = s["acc_fn"]()
    dati_ecg = s["ecg_fn"]() # Genera la lista di 10 valori

    return {
        "paziente_id": PAZIENTE_ID,
        "ecg_raw": dati_ecg,
        "rr_intervals": dati_ecg,  # <--- QUESTA CHIAVE SBLOCCHERÀ L'IA
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