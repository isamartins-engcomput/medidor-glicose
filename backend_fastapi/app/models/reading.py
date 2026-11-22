
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class ReadingCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)

    sensor: Literal["BME688"] = "BME688"

    temperature_c: float = Field(ge=-40, le=85)

    humidity_pct: float = Field(ge=0, le=100)

    pressure_hpa: float = Field(gt=0)

    gas_resistance_ohm: float = Field(gt=0)


class ReadingResponse(ReadingCreate):

    id: int

    received_at: datetime
