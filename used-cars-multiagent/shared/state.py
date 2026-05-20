from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


Status = Literal["acquired", "published", "negotiating", "sold", "rejected"]


class CarSaleState(BaseModel):
    car_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Status = "acquired"

    car_data: dict[str, Any] = Field(default_factory=dict)
    inspection_data: dict[str, Any] = Field(default_factory=dict)
    publication_data: dict[str, Any] = Field(default_factory=dict)
    lead_data: dict[str, Any] = Field(default_factory=dict)
    sale_data: dict[str, Any] = Field(default_factory=dict)

    negotiation_attempts: int = 0

    events: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_event(self, event: str) -> None:
        self.events.append(event)
        self.updated_at = datetime.now(timezone.utc)

    def to_summary(self) -> dict[str, Any]:
        return {
            "car_id": self.car_id,
            "status": self.status,
            "marca": self.car_data.get("marca"),
            "modelo": self.car_data.get("modelo"),
            "anio": self.car_data.get("año") or self.car_data.get("anio"),
            "km": self.car_data.get("km"),
            "precio_mercado": self.car_data.get("precio_mercado"),
            "precio_venta": self.car_data.get("precio_venta"),
            "apto_venta": self.car_data.get("apto_venta"),
            "lead_calificado": self.lead_data.get("lead_calificado"),
            "precio_final": self.sale_data.get("precio_final"),
            "venta_completada": self.sale_data.get("venta_completada"),
            "negotiation_attempts": self.negotiation_attempts,
            "updated_at": self.updated_at.isoformat(),
        }
