import numpy as np
import joblib
from .base_classifier import BaseClassifier

class PosturaClassifier(BaseClassifier):
    """
    Classificatore per la postura.
    Usa Random Forest addestrato su MHEALTH con feature engineering a finestre temporali.
    """

    def __init__(self, model_path: str):
        # Carica sia il modello che il dizionario etichette
        payload = joblib.load(model_path)
        self.modello = payload['modello']
        self.etichette = payload['etichette']
        
        # Buffer interno per accumulare i dati dell'accelerometro per le finestre live
        self.buffer = []
        self.WINDOW_SIZE = 100  # 2 secondi di dati a 50Hz
        self.STEP_SIZE = 50     # Quanti campioni scartare al passo successivo (overlap 50%)
        
        # Manteniamo l'ultima label predetta da restituire finché il buffer non si riempie nuovamente
        self.ultima_label = "in_accumulo"
        self.ultimo_score = 0.0

    def _calcola_feature_finestra(self, finestra_accel: np.ndarray) -> np.ndarray:
        """
        Calcola le 13 feature statistiche (identiche a quelle di train_postura.py)
        """
        medie = np.mean(finestra_accel, axis=0)
        stds = np.std(finestra_accel, axis=0)
        mins = np.min(finestra_accel, axis=0)
        maxs = np.max(finestra_accel, axis=0)
        sma = np.mean(np.sum(np.abs(finestra_accel), axis=1))
        
        # Ritorna un vettore riga (1, 13) pronto per scikit-learn
        return np.hstack([medie, stds, mins, maxs, sma]).reshape(1, -1)

    def predict(self, data: dict) -> dict:
        """
        Riceve l'accorrenza grezza, la inserisce nel buffer e restituisce
        la classificazione corrente basata sulla finestra mobile.
        """
        # Estrai i tre assi correnti dai campi del dizionario
        # Gestiamo sia chiavi corte che lunghe per massima compatibilità
        acc_x = data.get("acc_x") if data.get("acc_x") is not None else data.get("acc_torace_x", 0.0)
        acc_y = data.get("acc_y") if data.get("acc_y") is not None else data.get("acc_torace_y", 0.0)
        acc_z = data.get("acc_z") if data.get("acc_z") is not None else data.get("acc_torace_z", 0.0)
        
        # Aggiungiamo il campione corrente al buffer
        self.buffer.append([acc_x, acc_y, acc_z])

        # Se non abbiamo ancora abbastanza campioni, restituiamo l'ultimo stato noto (o di default)
        if len(self.buffer) < self.WINDOW_SIZE:
            return {"label": self.ultima_label, "score": self.ultimo_score}

        # Estraiamo gli ultimi WINDOW_SIZE elementi (matrice 100x3)
        matrice_finestra = np.array(self.buffer[-self.WINDOW_SIZE:])
        
        # Calcoliamo il vettore da 13 feature
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