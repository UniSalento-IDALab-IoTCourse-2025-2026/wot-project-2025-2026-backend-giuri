from .base_classifier import BaseClassifier

class TemperaturaClassifier(BaseClassifier):
    """
    Classificatore per la temperatura corporea.
    Basato su soglie cliniche standard — nessun modello ML.
    """

    def predict(self, data: dict) -> dict:
        """
        Args:
            data: {
                "temperatura": float  # in gradi Celsius
            }

        Returns:
            {
                "label": "ipotermia" | "normale" | "febbre" | "febbre_alta",
                "score": 1.0  # sempre 1.0, è una regola deterministica
            }
        """
        temp = data.get("temperatura", None)

        if temp is None:
            return {"label": "sconosciuta", "score": 0.0}

        if temp < 35.0:
            label = "ipotermia"
        elif temp <= 37.2:
            label = "normale"
        elif temp <= 39.0:
            label = "febbre"
        else:
            label = "febbre_alta"

        return {"label": label, "score": 1.0}