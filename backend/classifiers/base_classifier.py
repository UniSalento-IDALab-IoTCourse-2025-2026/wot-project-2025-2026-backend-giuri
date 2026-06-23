from abc import ABC, abstractmethod

class BaseClassifier(ABC):
    """
    Interfaccia comune per tutti i classificatori del sistema.
    Ogni classificatore deve implementare il metodo predict.
    """

    @abstractmethod
    def predict(self, data: dict) -> dict:
        """
        Riceve i dati grezzi e restituisce un dizionario
        con label e score.

        Args:
            data: dizionario con i dati del sensore

        Returns:
            dizionario con almeno:
            {
                "label": str,   # etichetta testuale
                "score": float  # confidenza (0-1)
            }
        """
        pass