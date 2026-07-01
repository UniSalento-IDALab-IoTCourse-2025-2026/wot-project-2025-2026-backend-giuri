import numpy as np
import joblib
from .base_classifier import BaseClassifier

class PosturaClassifier(BaseClassifier):
    """
    Classificatore per la postura.
    Usa Random Forest addestrato su MHEALTH (sensore da braccio/polso:
    accelerometro + giroscopio, 6 assi) con feature engineering a
    finestre temporali.

    Il punto di attacco anatomico è stato scelto al braccio invece che
    al petto perché in MHEALTH è l'unico sensore che espone sia
    accelerometro sia giroscopio — coerente con il dispositivo reale
    (IIT BioDataAcq), che sul canale IMU può fornire entrambi.

    NOTA SUL SAMPLE RATE (Bug #2): MHEALTH è campionato a 50Hz, ma il
    sensore IMU reale del dongle campiona a 104Hz. Le feature statistiche
    (media, std, min, max, SMA) devono essere calcolate su una finestra
    la cui *durata* corrisponde a quella vista in training (2s, overlap
    1s) — non sullo stesso numero di campioni. Per questo WINDOW_SIZE e
    STEP_SIZE qui sono derivati da IMU_RUNTIME_RATE (104Hz) e NON
    ricalcano i 100/50 campioni di train_postura.py, che restano
    corretti lì perché il dataset MHEALTH è nativamente a 50Hz.
    """

    IMU_RUNTIME_RATE = 104        # Hz reali del sensore IMU del dongle
    WINDOW_DURATION_SEC = 2.0     # deve combaciare con train_postura.py
    HOP_DURATION_SEC = 1.0        # overlap 50%, come in train_postura.py

    def __init__(self, model_path: str):
        # Carica sia il modello che il dizionario etichette
        payload = joblib.load(model_path)
        self.modello = payload['modello']
        self.etichette = payload['etichette']

        # Buffer interno per accumulare i dati IMU (acc+giro) per le finestre live.
        # Ogni elemento del buffer è un vettore a 6 componenti: [ax, ay, az, gx, gy, gz]
        self.buffer = []
        self.WINDOW_SIZE = int(self.IMU_RUNTIME_RATE * self.WINDOW_DURATION_SEC)  # 208 @ 104Hz
        self.STEP_SIZE = int(self.IMU_RUNTIME_RATE * self.HOP_DURATION_SEC)       # 104 @ 104Hz

        # Manteniamo l'ultima label predetta da restituire finché il buffer non si riempie nuovamente
        self.ultima_label = "in_accumulo"
        self.ultimo_score = 0.0

    def _calcola_feature_finestra(self, finestra_imu: np.ndarray) -> np.ndarray:
        """
        Calcola le 25 feature statistiche (identiche a quelle di train_postura.py):
        media, std, min, max per ciascuno dei 6 assi (acc_x,y,z + giro_x,y,z)
        più 1 SMA aggregato su tutti gli assi = 6*4 + 1 = 25 feature.
        """
        medie = np.mean(finestra_imu, axis=0)
        stds = np.std(finestra_imu, axis=0)
        mins = np.min(finestra_imu, axis=0)
        maxs = np.max(finestra_imu, axis=0)
        sma = np.mean(np.sum(np.abs(finestra_imu), axis=1))

        # Ritorna un vettore riga (1, 25) pronto per scikit-learn
        return np.hstack([medie, stds, mins, maxs, sma]).reshape(1, -1)

    def _estrai_assi(self, data: dict) -> list:
        """
        Estrae i sei assi correnti da un dizionario campione.
        Gestiamo sia chiavi corte che lunghe per massima compatibilità
        con eventuali payload storici/di test.
        """
        acc_x = data.get("acc_x") if data.get("acc_x") is not None else data.get("acc_braccio_x", 0.0)
        acc_y = data.get("acc_y") if data.get("acc_y") is not None else data.get("acc_braccio_y", 0.0)
        acc_z = data.get("acc_z") if data.get("acc_z") is not None else data.get("acc_braccio_z", 0.0)

        gyro_x = data.get("gyro_x") if data.get("gyro_x") is not None else data.get("giro_braccio_x", 0.0)
        gyro_y = data.get("gyro_y") if data.get("gyro_y") is not None else data.get("giro_braccio_y", 0.0)
        gyro_z = data.get("gyro_z") if data.get("gyro_z") is not None else data.get("giro_braccio_z", 0.0)

        return [acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z]

    def predict_batch(self, campioni: list) -> dict:
        """
        Riceve un'intera finestra di campioni IMU grezzi (tipicamente
        ~1s di dati a 104Hz, uno per messaggio MQTT) e li accoda tutti
        insieme al buffer interno, poi esegue la classificazione sulla
        finestra mobile se il buffer ha raggiunto WINDOW_SIZE.

        Sostituisce le chiamate ripetute a predict() con un singolo
        campione: prima della fix, un solo campione per messaggio MQTT
        (uno al secondo) riempiva il buffer con dati sotto-campionati
        di un fattore ~100 rispetto al segnale continuo atteso.

        Args:
            campioni: lista di dict, ciascuno con le chiavi
                acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z
        """
        for campione in campioni:
            self.buffer.append(self._estrai_assi(campione))

        if len(self.buffer) < self.WINDOW_SIZE:
            return {"label": self.ultima_label, "score": self.ultimo_score}

        # Estraiamo gli ultimi WINDOW_SIZE elementi (matrice WINDOW_SIZE x 6)
        matrice_finestra = np.array(self.buffer[-self.WINDOW_SIZE:])

        # Calcoliamo il vettore da 25 feature
        features = self._calcola_feature_finestra(matrice_finestra)

        # Predizione effettiva tramite Random Forest
        label_num = self.modello.predict(features)[0]
        prob = np.max(self.modello.predict_proba(features))

        # Mappatura etichetta stringa
        self.ultima_label = self.etichette.get(int(label_num), "sconosciuta")
        self.ultimo_score = round(float(prob), 4)

        # Avanzamento della Sliding Window (scartiamo i dati più vecchi per fare spazio ai nuovi)
        self.buffer = self.buffer[self.STEP_SIZE:]

        return {"label": self.ultima_label, "score": self.ultimo_score}

    def predict(self, data: dict) -> dict:
        """
        Compatibilità con chiamate a singolo campione (es. test unitari,
        script legacy, o payload senza imu_window). Delega internamente
        a predict_batch() con una finestra di un solo elemento.

        ATTENZIONE: se questo metodo viene chiamato una sola volta per
        messaggio MQTT (uno al secondo) anziché con l'intera finestra
        raccolta nell'intervallo, si ricade nel Bug #1 originale — il
        chiamante deve passare imu_window da mqtt_bridge.py tramite
        predict_batch(), non un campione alla volta via predict().
        """
        return self.predict_batch([data])