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

    # Gap massimo (in secondi) tra due letture anomale consecutive dello
    # stesso paziente perché vengano considerate parte dello stesso
    # episodio clinico. Sopra questa soglia si considera chiuso l'episodio
    # precedente e se ne apre uno nuovo.
    GAP_MASSIMO_EPISODIO_SECONDI = 10

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

    def find_episodi_anomalia_non_validati(
        self,
        gap_massimo_secondi: int = None
    ) -> list[dict]:
        """
        Raggruppa le anomalie non validate in "episodi clinici": letture
        anomale consecutive dello stesso paziente con un gap temporale
        inferiore a gap_massimo_secondi vengono considerate parte dello
        stesso evento (es. un episodio di fibrillazione atriale che dura
        30s genera una lettura anomala al secondo, ma clinicamente è un
        unico evento da validare una sola volta).

        Il raggruppamento avviene in Python dopo aver recuperato i
        documenti non validati: i volumi in gioco (anomalie in attesa di
        validazione, non l'intero storico) sono piccoli, e mantenere la
        logica in Python la rende più leggibile di un'aggregazione Mongo
        con bucket a gap dinamico.

        Restituisce una lista di episodi, ciascuno con:
        {
            "paziente_id": str,
            "annotation_ids": [str, ...],   # in ordine cronologico
            "timestamp_inizio": datetime,
            "timestamp_fine": datetime,
            "numero_letture": int,
            "ecg_score_max": float,
            "ecg_score_medio": float,
            "postura_label": str | None,      # dell'ultima lettura del cluster
            "temperatura_label": str,          # dell'ultima lettura del cluster
            "temperatura_valore": float,
            "documenti": [dict, ...]           # documenti originali, per dettaglio/espansione
        }
        ordinati per timestamp_fine decrescente (episodio più recente prima).
        """
        soglia = gap_massimo_secondi if gap_massimo_secondi is not None \
            else self.GAP_MASSIMO_EPISODIO_SECONDI

        # Ordiniamo per paziente e poi per timestamp crescente: è più
        # semplice rilevare i gap scorrendo in avanti nel tempo.
        documenti = list(
            self.collection.find({
                "ecg_label": "anomalo",
                "esito_medico": None
            }).sort([("paziente_id", 1), ("timestamp", 1)])
        )

        episodi = []
        cluster_corrente = []

        def chiudi_cluster():
            if not cluster_corrente:
                return
            episodi.append(self._costruisci_episodio(cluster_corrente))

        for doc in documenti:
            if not cluster_corrente:
                cluster_corrente.append(doc)
                continue

            precedente = cluster_corrente[-1]
            stesso_paziente = doc["paziente_id"] == precedente["paziente_id"]
            gap = (doc["timestamp"] - precedente["timestamp"]).total_seconds()

            if stesso_paziente and gap <= soglia:
                cluster_corrente.append(doc)
            else:
                chiudi_cluster()
                cluster_corrente = [doc]

        chiudi_cluster()

        # Più recenti prima, coerente con l'ordinamento di
        # find_anomalie_non_validate()
        episodi.sort(key=lambda e: e["timestamp_fine"], reverse=True)
        return episodi

    def find_episodi_per_paziente(
        self,
        paziente_id: str,
        gap_massimo_secondi: int = None
    ) -> list[dict]:
        """
        Variante di find_episodi_anomalia_non_validati() per un singolo
        paziente, usata dall'app paziente per mostrare le anomalie nello
        stesso identico raggruppamento in episodi clinici visto dal medico
        (stessa soglia di gap temporale, stessa logica di clustering).

        Differenza principale rispetto alla vista medico: qui NON si
        filtra per esito_medico — vengono inclusi sia gli episodi ancora
        in attesa di validazione sia quelli già validati, così il
        paziente vede anche l'esito (vero_positivo / falso_allarme) e le
        eventuali note lasciate dal medico.

        Dato che si lavora già su un singolo paziente non serve
        raggruppare anche per paziente_id: il clustering considera solo
        il gap temporale tra letture consecutive.

        Restituisce una lista di episodi (stesso formato di
        _costruisci_episodio, quindi con annotation_ids, intervallo
        temporale, score aggregati e documenti grezzi del cluster),
        ordinati per timestamp_fine decrescente (più recente prima).
        """
        soglia = gap_massimo_secondi if gap_massimo_secondi is not None \
            else self.GAP_MASSIMO_EPISODIO_SECONDI

        documenti = list(
            self.collection.find({
                "paziente_id": paziente_id,
                "ecg_label": "anomalo",
            }).sort("timestamp", 1)
        )

        episodi = []
        cluster_corrente = []

        def chiudi_cluster():
            if not cluster_corrente:
                return
            episodi.append(self._costruisci_episodio(cluster_corrente))

        for doc in documenti:
            if not cluster_corrente:
                cluster_corrente.append(doc)
                continue

            precedente = cluster_corrente[-1]
            gap = (doc["timestamp"] - precedente["timestamp"]).total_seconds()

            if gap <= soglia:
                cluster_corrente.append(doc)
            else:
                chiudi_cluster()
                cluster_corrente = [doc]

        chiudi_cluster()

        episodi.sort(key=lambda e: e["timestamp_fine"], reverse=True)
        return episodi

    def _costruisci_episodio(self, cluster: list[dict]) -> dict:
        """Aggrega un cluster di documenti (stesso paziente, gap contiguo) in un episodio."""
        ultima = cluster[-1]
        scores = [d.get("ecg_score", 0.0) for d in cluster]

        return {
            "paziente_id": cluster[0]["paziente_id"],
            "annotation_ids": [str(d["_id"]) for d in cluster],
            "timestamp_inizio": cluster[0]["timestamp"],
            "timestamp_fine": ultima["timestamp"],
            "numero_letture": len(cluster),
            "ecg_score_max": max(scores) if scores else 0.0,
            "ecg_score_medio": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "postura_label": ultima.get("postura_label"),
            "temperatura_label": ultima.get("temperatura_label"),
            "temperatura_valore": ultima.get("temperatura_valore"),
            "esito_medico": ultima.get("esito_medico"),
            "note_medico": ultima.get("note_medico"),
            "validato_at": ultima.get("validato_at"),
            "documenti": cluster
        }

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

    def update_esito_medico_multiplo(
        self,
        annotation_ids: list[str],
        esito: EsitoMedico,
        note: str = None
    ) -> int:
        """
        Applica lo stesso esito medico a un gruppo di annotazioni in una
        sola operazione — usato per validare un intero episodio clinico
        (più letture anomale consecutive raggruppate da
        find_episodi_anomalia_non_validati) con una sola azione del medico.

        Restituisce il numero di documenti effettivamente aggiornati.
        """
        if not annotation_ids:
            return 0

        aggiornamento = {
            "$set": {
                "esito_medico": esito,
                "validato_at": datetime.now(timezone.utc),
                "note_medico": note
            }
        }
        risultato = self.collection.update_many(
            {"_id": {"$in": [ObjectId(aid) for aid in annotation_ids]}},
            aggiornamento
        )
        return risultato.modified_count

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