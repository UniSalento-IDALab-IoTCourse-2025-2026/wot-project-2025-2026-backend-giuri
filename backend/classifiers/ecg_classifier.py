import os
import numpy as np
import joblib
from .base_classifier import BaseClassifier

# Soglia per mappare la probabilità in due label
SOGLIA_ANOMALO = 0.5


class ECGClassifier(BaseClassifier):
    """
    Classificatore per il segnale ECG/R-R.
    Usa Random Forest addestrato su chfdb.

    Hot-reload: il retrain periodico (retrain_scheduler.py) gira in un
    processo separato da mqtt_subscriber.py / fastapi_server.py e
    sovrascrive ecg_model.pkl sul filesystem. Per evitare un meccanismo
    di IPC tra processi, ogni istanza di ECGClassifier controlla il
    mtime del file prima di ogni predizione: se è cambiato rispetto
    all'ultimo caricamento, ricarica il modello da disco. Il controllo
    costa una sola os.stat() per chiamata — trascurabile rispetto
    all'inferenza stessa.
    """

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._ultimo_mtime = None
        self.modello = None
        self._carica_modello()

    def _carica_modello(self) -> None:
        self.modello = joblib.load(self.model_path)
        # Il modello è stato addestrato con n_jobs=-1 (utile in fase di
        # training/batch), ma qui si predice UN campione alla volta in
        # tempo reale ad ogni messaggio MQTT: parallelizzare i 100 alberi
        # su più core per una singola predizione è puro overhead e, in
        # alcune versioni di scikit-learn/joblib, genera un warning
        # cosmetico ("delayed should be used with Parallel..."). Forzare
        # n_jobs=1 a runtime elimina sia l'overhead sia il warning, senza
        # dover ri-addestrare il modello (n_jobs è un iperparametro letto
        # a ogni predict/predict_proba, non un dato "cotto" nei pesi).
        self.modello.n_jobs = 1
        self._ultimo_mtime = os.path.getmtime(self.model_path)

    def _controlla_reload(self) -> None:
        """
        Ricarica il modello se il file su disco è più recente
        dell'ultima versione caricata in memoria (es. dopo un
        ri-addestramento completato da retrain_scheduler.py).
        """
        try:
            mtime_corrente = os.path.getmtime(self.model_path)
        except OSError:
            # File temporaneamente non disponibile (es. in scrittura
            # durante joblib.dump): si continua con il modello già
            # caricato in memoria, si ritenterà alla prossima chiamata.
            return

        if self._ultimo_mtime is None or mtime_corrente > self._ultimo_mtime:
            try:
                self._carica_modello()
                print(f"[ECGClassifier] Modello ricaricato da {self.model_path} "
                      f"(mtime aggiornato)")
            except Exception as e:
                # Il file potrebbe essere ancora a metà scrittura (race
                # con joblib.dump del retrain): non propaghiamo l'errore,
                # restiamo sul modello precedente e ritentiamo dopo.
                print(f"[ECGClassifier] Reload fallito, mantengo il modello "
                      f"corrente: {e}")

    def _estrai_features(self, rr_intervals: list) -> np.ndarray:
        """
        Estrae le stesse feature usate durante il training.
        """
        rr = np.array(rr_intervals)
        return np.array([[
            np.mean(rr),
            np.std(rr),
            np.min(rr),
            np.max(rr),
            np.max(rr) - np.min(rr)
        ]])

    def predict(self, data: dict) -> dict:
        """
        Args:
            data: {
                "rr_intervals": [0.82, 0.79, 0.81, ...]  # lista di 10 valori
            }

        Returns:
            {
                "label": "normale" | "anomalo",
                "score": float
            }
        """
        self._controlla_reload()

        rr = data.get("rr_intervals", [])

        if len(rr) < 10:
            return {"label": "normale", "score": 0.0}

        features = self._estrai_features(rr[-10:])

        # predict_proba restituisce [prob_normale, prob_anomalo]
        prob = self.modello.predict_proba(features)[0][1]

        label = "anomalo" if prob >= SOGLIA_ANOMALO else "normale"

        return {"label": label, "score": round(float(prob), 4)}