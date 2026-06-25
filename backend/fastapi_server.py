import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

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

ECG_MODEL_PATH = "backend/ai/trained/ecg_model.pkl"
POSTURA_MODEL_PATH = "backend/ai/trained/postura_model.pkl"

# ============================================================
# APP FASTAPI
# ============================================================

app = FastAPI(
    title="CardioSense API",
    description="API per il monitoraggio dello scompenso cardiaco",
    version="1.0.0"
)

# CORS — permette alla dashboard web di chiamare le API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================
# AUTENTICAZIONE JWT
# ============================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def crea_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_medico_corrente(
    token: str = Depends(oauth2_scheme),
    session=Depends(get_session)
):
    """
    Dependency injection — verifica il JWT e restituisce
    il medico autenticato. Usata per proteggere gli endpoint.
    """
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
# SCHEMI PYDANTIC PER REQUEST/RESPONSE
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


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup():
    """
    Inizializza il database MySQL all'avvio.
    """
    init_db()
    print("CardioSense API avviata")


# ============================================================
# ENDPOINT AUTENTICAZIONE
# ============================================================

@app.post("/auth/registrazione", tags=["Auth"])
def registra_medico(
    body: RegistrazioneRequest,
    session=Depends(get_session)
):
    """
    Registra un nuovo medico nel sistema.
    """
    repo = UserRepository(session)

    # Verifica che l'email non sia già registrata
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
    """
    Login medico — restituisce JWT.
    """
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
    """
    Crea un nuovo paziente associato al medico autenticato.
    Restituisce il codice di accesso generato.
    """
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
    """
    Restituisce tutti i pazienti del medico autenticato.
    """
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

@app.get("/anomalie", tags=["Annotazioni"])
def get_anomalie_non_validate(
    medico: Medico = Depends(get_medico_corrente)
):
    """
    Restituisce le anomalie non ancora validate dal medico.
    Usato dalla dashboard per il polling.
    """
    db = get_db()
    repo = AnnotationRepository(db)
    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ECGClassifier(ECG_MODEL_PATH),
        postura_classifier=PosturaClassifier(POSTURA_MODEL_PATH),
        temperatura_classifier=TemperaturaClassifier()
    )
    anomalie = service.get_anomalie_non_validate()

    # Converti ObjectId in stringa per la serializzazione JSON
    for a in anomalie:
        a["_id"] = str(a["_id"])

    return anomalie


@app.get("/pazienti/{paziente_id}/storico", tags=["Annotazioni"])
def get_storico_paziente(
    paziente_id: str,
    limit: int = 50,
    medico: Medico = Depends(get_medico_corrente)
):
    """
    Restituisce lo storico delle annotazioni di un paziente.
    """
    db = get_db()
    repo = AnnotationRepository(db)
    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ECGClassifier(ECG_MODEL_PATH),
        postura_classifier=PosturaClassifier(POSTURA_MODEL_PATH),
        temperatura_classifier=TemperaturaClassifier()
    )
    storico = service.get_storico_paziente(paziente_id, limit)

    for a in storico:
        a["_id"] = str(a["_id"])

    return storico


@app.patch("/anomalie/{annotation_id}/valida", tags=["Annotazioni"])
def valida_anomalia(
    annotation_id: str,
    body: ValidazioneRequest,
    medico: Medico = Depends(get_medico_corrente)
):
    """
    Il medico approva o nega un'anomalia.
    Aggiorna il documento MongoDB con esito_medico.
    """
    db = get_db()
    repo = AnnotationRepository(db)
    service = AnnotationService(
        annotation_repo=repo,
        ecg_classifier=ECGClassifier(ECG_MODEL_PATH),
        postura_classifier=PosturaClassifier(POSTURA_MODEL_PATH),
        temperatura_classifier=TemperaturaClassifier()
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
        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )