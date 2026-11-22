
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from app.models.reading import ReadingCreate, ReadingResponse

from app.core.database import (
    save_reading,
    get_readings,
    get_latest_reading
)


router = APIRouter()


# Recebe e armazena uma medicao

@router.post("", response_model=ReadingResponse, status_code=201)
def create_reading(reading: ReadingCreate):

    try:

        return save_reading(reading)

    except sqlite3.Error:

        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar medicao no banco de dados."
        )


# Consulta o historico

@router.get("", response_model=list[ReadingResponse])
def read_history(
    limit: int = Query(default=50, ge=1, le=500)
):

    return get_readings(limit)


# Consulta a ultima medicao

@router.get("/latest", response_model=ReadingResponse)
def read_latest():

    reading = get_latest_reading()

    if reading is None:

        raise HTTPException(
            status_code=404,
            detail="Nenhuma medicao encontrada."
        )

    return reading
