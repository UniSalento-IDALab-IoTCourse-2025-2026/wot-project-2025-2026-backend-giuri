import os
import bcrypt  # <--- Sostituito passlib con bcrypt nativo
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from db.mongo_client import get_db
from db.mysql_client import get_session, init_db
from models.user import Medico, Paziente
from models.annotation import EsitoMedico
from repositories.annotation_repository import AnnotationRepository
from repositories.user_repository import UserRepository
from services.annotation_service import AnnotationService
from classifiers.ecg_classifier import ECGClassifier
from classifiers.postura_classifier import PosturaClassifier
from classifiers.temperatura_classifier import TemperaturaClassifier

load_dotenv()

# ============================================================
# CONFIGURAZIONE
# ============================================================

SECRET_KEY = os.getenv("JWT_SECRET", "cambia_questa_chiave")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 ore

ECG_MODEL_PATH = "ai/trained/ecg_model.pkl"
POSTURA_MODEL_PATH = "ai/trained/postura_model.pkl"

# Dizionario globale per mantenere i classificatori in memoria
ml_models = {}

# ============================================================
# LIFESPAN (Gestione di Startup e Shutdown unificata)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    init_db()

    # Carica i modelli di IA in memoria UNA VOLTA SOLA
    ml_models["ecg"] = ECGClassifier(ECG_MODEL_PATH)
    ml_models["postura"] = PosturaClassifier(POSTURA_MODEL_PATH)
    ml_models["temperatura"] = TemperaturaClassifier()

    print("CardioSense API avviata e modelli IA caricati correttamente")

    yield

    # --- SHUTDOWN ---
    ml_models.clear()
    print("CardioSense API spenta")


# ============================================================
# APP FASTAPI
# ============================================================

app = FastAPI(
    title="CardioSense API",
    description="API per il monitoraggio dello scompenso cardiaco",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================
# AUTENTICAZIONE JWT (Modificata con Bcrypt nativo)
# ============================================================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    """Genera l'hash della password usando direttamente bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica la password in chiaro contro l'hash memorizzato."""
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def crea_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_medico_corrente(
    token: str = Depends(oauth2_scheme),
    session=Depends(get_session)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token non valido o scaduto",
        headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    repo = UserRepository(session)
    medico = repo.find_medico_by_email(email)
    if medico is None:
        raise credentials_exception
    return medico


# ============================================================
# SCHEMI PYDANTIC
# ============================================================

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegistrazioneRequest(BaseModel):
    nome: str
    cognome: str
    email: str
    password: str


class PazienteRequest(BaseModel):
    nome: str
    cognome: str


class PazienteResponse(BaseModel):
    id: int
    nome: str
    cognome: str
    codice_accesso: str


class ValidazioneRequest(BaseModel):
    esito: EsitoMedico
    note: Optional[str] = None


class ValidazioneEpisodioRequest(BaseModel):
    annotation_ids: list[str]
    esito: EsitoMedico
    note: Optional[str] = None


# ============================================================
# ENDPOINT AUTENTICAZIONE
# ============================================================

@app.post("/auth/registrazione", tags=["Auth"])
def registra_medico(
    body: RegistrazioneRequest,
    session=Depends(get_session)
):
    repo = UserRepository(session)
    esistente = repo.find_medico_by_email(body.email)
    if esistente:
        raise HTTPException(
            status_code=400,
            detail="Email già registrata"
        )

    medico = Medico(
        nome=body.nome,
        cognome=body.cognome,
        email=body.email,
        password_hash=hash_password(body.password)
    )
    repo.save_medico(medico)
    return {"messaggio": "Medico registrato con successo"}


@app.post("/auth/login", response_model=LoginResponse, tags=["Auth"])
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session=Depends(get_session)
):
    repo = UserRepository(session)
    medico = repo.find_medico_by_email(form.username)

    if not medico or not verify_password(form.password, medico.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide"
        )

    token = crea_token({"sub": medico.email})
    return LoginResponse(access_token=token)


# ============================================================
# ENDPOINT PAZIENTI
# ============================================================

@app.post("/pazienti", response_model=PazienteResponse, tags=["Pazienti"])
def crea_paziente(
    body: PazienteRequest,
    medico: Medico = Depends(get_medico_corrente),
    session=Depends(get_session)
):
    repo = UserRepository(session)
    paziente = repo.save_paziente(
        nome=body.nome,
        cognome=body.cognome,
        medico_id=medico.id
    )
    return PazienteResponse(
        id=paziente.id,
        nome=paziente.nome,
        cognome=paziente.cognome,
        codice_accesso=paziente.codice_accesso
    )


@app.get("/pazienti", tags=["Pazienti"])
def lista_pazienti(
    medico: Medico = Depends(get_medico_corrente),
    session=Depends(get_session)
):
    repo = UserRepository(session)
    pazienti = repo.find_pazienti_by_medico(medico.id)
    return [
        {
            "id": p.id,
            "nome": p.nome,
            "cognome": p.cognome,
            "codice_accesso": p.codice_accesso
        }
        for p in pazienti
    ]


# ============================================================
# ENDPOINT ANNOTAZIONI
# ============================================================

def _arricchisci_con_dati_paziente(elementi: list[dict], session) -> None:
    """
    Arricchisce in-place una lista di dict (anomalie o episodi) con
    nome/cognome del paziente da MySQL, dato paziente_id (= codice_accesso).
    Centralizzato qui perché serve sia per /anomalie che per /anomalie/episodi.
    """
    user_repo = UserRepository(session)
    cache_pazienti: dict[str, Paziente | None] = {}

    for el in elementi:
        codice = el.get("paziente_id", "")
        if codice not in cache_pazienti:
            cache_pazienti[codice] = user_repo.find_paziente_by_codice(codice)

        paziente = cache_pazienti[codice]
        if paziente:
            el["paziente_nome"] = paziente.nome
            el["paziente_cognome"] = paziente.cognome
        else:
            el["paziente_nome"] = None
            el["paziente_cognome"] = None


@app.get("/anomalie", tags=["Annotazioni"])
def get_anomalie_non_validate(
    medico: Medico = Depends(get_medico_corrente),
    session=Depends(get_session)
):
    """
    Restituisce le anomalie non validate come righe singole (una per
    lettura). Mantenuto per compatibilità/debug; la dashboard usa
    /anomalie/episodi per la vista raggruppata.
    """
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    anomalie = service.get_anomalie_non_validate()

    for a in anomalie:
        a["_id"] = str(a["_id"])

    _arricchisci_con_dati_paziente(anomalie, session)
    return anomalie


@app.get("/anomalie/episodi", tags=["Annotazioni"])
def get_episodi_anomalia_non_validati(
    medico: Medico = Depends(get_medico_corrente),
    session=Depends(get_session)
):
    """
    Restituisce le anomalie non validate raggruppate per episodio
    clinico: letture anomale consecutive dello stesso paziente con un
    gap temporale ridotto (default 10s, vedi
    AnnotationRepository.GAP_MASSIMO_EPISODIO_SECONDI) vengono unite in
    un solo elemento, in modo che il medico veda e validi un episodio
    di fibrillazione atriale di 30 letture come UNA riga, non trenta.

    I documenti grezzi di ciascun episodio restano disponibili nel
    campo "documenti" per chi vuole espandere il dettaglio o per il
    grafico ECG esteso, ma con _id già convertiti in stringa.
    """
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    episodi = service.get_episodi_anomalia_non_validati()

    # Conversione ObjectId -> str nei documenti grezzi annidati
    for ep in episodi:
        for doc in ep.get("documenti", []):
            doc["_id"] = str(doc["_id"])

    _arricchisci_con_dati_paziente(episodi, session)
    return episodi

@app.get("/pazienti/by-codice/{codice}", tags=["Pazienti"])
def valida_codice_paziente(codice: str, session=Depends(get_session)):
    """Endpoint pubblico: l'app paziente lo usa per validare il codice di accesso."""
    repo = UserRepository(session)
    paziente = repo.find_paziente_by_codice(codice)
    if not paziente:
        raise HTTPException(status_code=404, detail="Codice non valido")
    return {
        "id": paziente.id,
        "nome": paziente.nome,
        "cognome": paziente.cognome,
        "codice_accesso": paziente.codice_accesso,
    }


@app.get("/pazienti/by-codice/{codice}/storico", tags=["Pazienti"])
def storico_pubblico_paziente(codice: str, limit: int = 50):
    """
    Variante pubblica di get_storico_paziente, usata dall'app paziente
    (che non ha un token medico). paziente_id nelle annotazioni == codice_accesso.

    Restituisce TUTTE le annotazioni (anche quelle normali): rimane
    pensata per un eventuale storico completo, ma il popup "Anomalie"
    dell'app paziente NON deve usare questo endpoint — deve usare
    /pazienti/by-codice/{codice}/episodi qui sotto, che filtra e
    raggruppa solo gli eventi anomali.
    """
    db = get_db()
    repo = AnnotationRepository(db)
    storico = repo.find_by_patient(codice, limit)
    for a in storico:
        a["_id"] = str(a["_id"])
    return storico


@app.get("/pazienti/by-codice/{codice}/episodi", tags=["Pazienti"])
def episodi_pubblico_paziente(codice: str):
    """
    Endpoint pubblico per l'app paziente: restituisce SOLO gli episodi
    anomali del paziente (codice_accesso == paziente_id), raggruppati
    esattamente come nella vista medico (stessa soglia di gap temporale
    di AnnotationRepository.GAP_MASSIMO_EPISODIO_SECONDI), così un
    episodio di 30 letture anomale consecutive appare come un solo
    evento anche qui — non 30 righe.

    A differenza di /anomalie/episodi (vista medico, solo non validati),
    qui vengono restituiti sia gli episodi in attesa di validazione sia
    quelli già validati, in modo che il paziente possa vedere anche
    l'esito (vero_positivo / falso_allarme) e le eventuali note del
    medico una volta disponibili.

    I documenti grezzi di ciascun episodio hanno _id già convertiti in
    stringa, come per l'analogo endpoint medico.
    """
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    episodi = service.get_episodi_per_paziente(codice)

    for ep in episodi:
        for doc in ep.get("documenti", []):
            doc["_id"] = str(doc["_id"])

    return episodi


@app.get("/pazienti/{paziente_id}/storico", tags=["Annotazioni"])
def get_storico_paziente(
    paziente_id: str,
    limit: int = 50,
    medico: Medico = Depends(get_medico_corrente)
):
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    storico = service.get_storico_paziente(paziente_id, limit)

    for a in storico:
        a["_id"] = str(a["_id"])

    return storico


@app.get("/annotazioni/{annotation_id}", tags=["Annotazioni"])
def get_annotazione(
    annotation_id: str,
    medico: Medico = Depends(get_medico_corrente)
):
    """
    Recupera una singola annotazione — usato dalla dashboard per
    aggiornare la finestra ECG estesa una volta che è pronta.
    """
    db = get_db()
    repo = AnnotationRepository(db)
    doc = repo.find_by_id(annotation_id)

    if not doc:
        raise HTTPException(status_code=404, detail="Annotazione non trovata")

    doc["_id"] = str(doc["_id"])
    return doc


@app.patch("/anomalie/episodi/valida", tags=["Annotazioni"])
def valida_episodio(
    body: ValidazioneEpisodioRequest,
    medico: Medico = Depends(get_medico_corrente)
):
    """
    Valida in un colpo solo tutte le letture di un episodio clinico
    (gli annotation_ids restituiti da GET /anomalie/episodi per quella
    riga). Lo stesso esito e la stessa nota vengono scritti su ciascun
    documento — il dato grezzo per il retraining resta granulare per
    singola lettura, cambia solo l'azione che il medico deve compiere.
    """
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    numero_aggiornati = service.valida_episodio(
        body.annotation_ids,
        body.esito,
        body.note
    )

    if numero_aggiornati == 0:
        raise HTTPException(
            status_code=404,
            detail="Nessuna annotazione trovata per l'episodio indicato"
        )

    return {
        "messaggio": "Episodio validato con successo",
        "letture_aggiornate": numero_aggiornati
    }


@app.patch("/anomalie/{annotation_id}/valida", tags=["Annotazioni"])
def valida_anomalia(
    annotation_id: str,
    body: ValidazioneRequest,
    medico: Medico = Depends(get_medico_corrente)
):
    """Valida una singola lettura anomala. Mantenuto per compatibilità/debug."""
    db = get_db()
    repo = AnnotationRepository(db)

    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ml_models["ecg"],
        postura_classifier=ml_models["postura"],
        temperatura_classifier=ml_models["temperatura"]
    )
    successo = service.valida_anomalia(
        annotation_id,
        body.esito,
        body.note
    )

    if not successo:
        raise HTTPException(
            status_code=404,
            detail="Annotazione non trovata"
        )

    return {"messaggio": "Anomalia validata con successo"}



# ============================================================
# ENDPOINT SALUTE SISTEMA
# ============================================================

@app.get("/health", tags=["Sistema"])
def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=8443,
        ssl_keyfile="../mosquitto/certs/server.key",
        ssl_certfile="../mosquitto/certs/server.crt",
        reload=True
    )