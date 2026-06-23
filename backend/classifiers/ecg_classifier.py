import numpy as np
import joblib
from .base_classifier import BaseClassifier

# Soglia per mappare la probabilità in due label
SOGLIA_ANOMALO = 0.5

class ECGClassifier(BaseClassifier):
    """
    Classificatore per il segnale ECG/R-R.
    Usa Random Forest addestrato su chfdb.
    """

    def __init__(self, model_path: str):
        self.modello = joblib.load(model_path)

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
        rr = data.get("rr_intervals", [])

        if len(rr) < 10:
            return {"label": "normale", "score": 0.0}

        features = self._estrai_features(rr[-10:])

        # predict_proba restituisce [prob_normale, prob_anomalo]
        prob = self.modello.predict_proba(features)[0][1]

        label = "anomalo" if prob >= SOGLIA_ANOMALO else "normale"

        return {"label": label, "score": round(float(prob), 4)}