
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as readings_router

from app.core.database import init_db


# Inicializacao do banco de dados

@asynccontextmanager
async def lifespan(app: FastAPI):

    init_db()

    yield


# Criacao da aplicacao

app = FastAPI(

    title="Medidor de Glicose Acessivel",

    description="API para recebimento e gerenciamento das leituras do BME688.",

    version="0.1.0",

    lifespan=lifespan
)


# Configuracao de comunicacao com o aplicativo

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=False,

    allow_methods=["GET", "POST"],

    allow_headers=["*"]

)


# Registro das rotas

app.include_router(

    readings_router,

    prefix="/api/v1/readings",

    tags=["Leituras"]

)


# Verificacao de funcionamento

@app.get("/health", tags=["Sistema"])
def health_check():

    return {

        "status": "online",

        "service": "medidor-glicose-api",

        "version": "0.1.0"

    }
