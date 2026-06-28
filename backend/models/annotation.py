from pydantic import BaseModel, Field
from datetime import datetime, timezone
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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Etichette dei tre classificatori
    ecg_label: ECGLabel
    ecg_score: float
    rr_intervals: Optional[list[float]] = None

    # Istantanea ECG raw per visualizzazione clinica nel modal di validazione.
    # Contiene i campioni grezzi (normalizzati in float) della finestra di
    # acquisizione centrata sull'evento — tipicamente 250 campioni (1s a 250Hz).
    ecg_raw_snapshot: Optional[list[float]] = None

    postura_label: Optional[str] = None
    postura_score: Optional[float] = None
    temperatura_label: TemperaturaLabel
    temperatura_valore: float

    # Tipo di annotazione
    tipo_annotazione: TipoAnnotazione = TipoAnnotazione.AUTOMATICA

    # Aggiunto dal medico dopo la validazione
    esito_medico: Optional[EsitoMedico] = None
    note_medico: Optional[str] = None
    validato_at: Optional[datetime] = None

    # Finestra ECG estesa (≥30s, prima e dopo l'anomalia), popolata in modo
    # asincrono da AnnotationService non appena il buffer accumula anche
    # i campioni successivi all'evento. Finché non è pronta, il medico
    # vede solo ecg_raw_snapshot (1s) come anteprima immediata.
    ecg_window: Optional[list[float]] = None
    ecg_window_sample_rate: int = 250
    ecg_window_anomalia_index: Optional[int] = None
    ecg_window_pronta: bool = False

    class Config:
        use_enum_values = True