import numpy as np
import joblib
from .base_classifier import BaseClassifier

class PosturaClassifier(BaseClassifier):
    """
    Classificatore per la postura.
    Usa Random Forest addestrato su MHEALTH.
    """

    def __init__(self, model_path: str):
        # Carica sia il modello che il dizionario etichette
        payload = joblib.load(model_path)
        self.modello = payload['modello']
        self.etichette = payload['etichette']

    def predict(self, data: dict) -> dict:
        """
        Args:
            data: {
                "acc_x": float,
                "acc_y": float,
                "acc_z": float
            }

        Returns:
            {
                "label": "camminata" | "seduto" | "sdraiato" | ...,
                "score": float
            }
        """
        acc = np.array([[
            data.get("acc_x", 0.0),
            data.get("acc_y", 0.0),
            data.get("acc_z", 0.0)
        ]])

        label_num = self.modello.predict(acc)[0]
        prob = np.max(self.modello.predict_proba(acc))
        label = self.etichette.get(int(label_num), "sconosciuta")

        return {"label": label, "score": round(float(prob), 4)}