from pymongo.database import Database
from pymongo import DESCENDING
from bson import ObjectId
from datetime import datetime, timezone
from models.annotation import Annotation, EsitoMedico


class AnnotationRepository:
    """
    Gestisce tutte le operazioni CRUD sulle annotazioni su MongoDB.
    """

    COLLECTION = "annotations"

    def __init__(self, db: Database):
        self.collection = db[self.COLLECTION]

    def save(self, annotation: Annotation) -> str:
        """
        Salva una nuova annotazione su MongoDB.
        Restituisce l'ID del documento inserito.
        """
        documento = annotation.model_dump()
        risultato = self.collection.insert_one(documento)
        return str(risultato.inserted_id)

    def find_by_patient(
        self,
        paziente_id: str,
        limit: int = 50
    ) -> list[dict]:
        """
        Restituisce le ultime N annotazioni di un paziente,
        ordinate per timestamp decrescente.
        """
        return list(
            self.collection
            .find({"paziente_id": paziente_id})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )

    def find_anomalie_non_validate(self) -> list[dict]:
        """
        Restituisce tutte le annotazioni anomale
        che il medico non ha ancora validato.
        """
        return list(
            self.collection.find({
                "ecg_label": "anomalo",
                "esito_medico": None
            }).sort("timestamp", DESCENDING)
        )

    def update_esito_medico(
        self,
        annotation_id: str,
        esito: EsitoMedico,
        note: str = None
    ) -> bool:
        """
        Aggiorna un documento esistente con la validazione del medico.
        Restituisce True se l'aggiornamento è andato a buon fine.
        """
        aggiornamento = {
            "$set": {
                "esito_medico": esito,
                "validato_at": datetime.now(timezone.utc),
                "note_medico": note
            }
        }
        risultato = self.collection.update_one(
            {"_id": ObjectId(annotation_id)},
            aggiornamento
        )
        return risultato.modified_count > 0

    def find_validated_for_retraining(self) -> list[dict]:
        """
        Restituisce tutte le annotazioni validate dal medico
        da usare per il ri-addestramento del modello.
        """
        return list(
            self.collection.find({
                "esito_medico": {"$ne": None}
            })
        )
    
    def update_ecg_window(
        self,
        annotation_id: str,
        finestra: list,
        indice_anomalia: int,
        sample_rate: int = 250
    ) -> bool:
        """
        Aggiorna l'annotazione con la finestra ECG estesa (≥30s, prima e
        dopo l'anomalia), calcolata in modo asincrono una volta che il
        buffer ha accumulato anche i campioni successivi all'evento.
        """
        aggiornamento = {
            "$set": {
                "ecg_window": finestra,
                "ecg_window_anomalia_index": indice_anomalia,
                "ecg_window_sample_rate": sample_rate,
                "ecg_window_pronta": True
            }
        }
        risultato = self.collection.update_one(
            {"_id": ObjectId(annotation_id)},
            aggiornamento
        )
        return risultato.modified_count > 0

    def find_by_id(self, annotation_id: str) -> dict | None:
        """Recupera una singola annotazione (usato per il refresh della finestra ECG)."""
        return self.collection.find_one({"_id": ObjectId(annotation_id)})