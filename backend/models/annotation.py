from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class ECGLabel(str, Enum):
    NORMALE = "normale"
    ANOMALO = "anomalo"


class TemperaturaLabel(str, Enum):
    IPOTERMIA = "ipotermia"
    NORMALE = "normale"
    FEBBRE = "febbre"
    FEBBRE_ALTA = "febbre_alta"
    SCONOSCIUTA = "sconosciuta"


class TipoAnnotazione(str, Enum):
    AUTOMATICA = "automatica"
    CLINICA = "clinica"
    SINTOMATICA = "sintomatica"
    PRESCRITTA = "prescritta"


class EsitoMedico(str, Enum):
    VERO_POSITIVO = "vero_positivo"
    FALSO_ALLARME = "falso_allarme"


class Annotation(BaseModel):
    """
    Schema del documento MongoDB per ogni lettura dei sensori.
    """
    paziente_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Etichette dei tre classificatori
    ecg_label: ECGLabel
    ecg_score: float
    postura_label: str
    postura_score: float
    temperatura_label: TemperaturaLabel
    temperatura_valore: float

    # Tipo di annotazione
    tipo_annotazione: TipoAnnotazione = TipoAnnotazione.AUTOMATICA

    # Aggiunto dal medico dopo la validazione
    esito_medico: Optional[EsitoMedico] = None
    note_medico: Optional[str] = None
    validato_at: Optional[datetime] = None

    class Config:
        use_enum_values = True