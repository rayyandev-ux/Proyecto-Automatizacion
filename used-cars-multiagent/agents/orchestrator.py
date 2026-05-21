from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from rich.console import Console

from agents.acquisition_agent import AcquisitionAgent
from agents.crm_chatbot_agent import CRMChatbotAgent
from agents.publication_agent import PublicationAgent
from agents.sales_closing_agent import SalesClosingAgent
from shared.event_bus import (
    CAR_ACQUIRED,
    Event,
    EventBus,
    LEAD_QUALIFIED,
    PUBLISHED,
    SALE_COMPLETED,
)
from shared.state import CarSaleState


class Orchestrator:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.console = Console()
        self.event_bus = EventBus()

        self.acquisition_agent = AcquisitionAgent(api_key=api_key, event_bus=self.event_bus, model=model)
        self.publication_agent = PublicationAgent(api_key=api_key, event_bus=self.event_bus, model=model)
        self.crm_chatbot_agent = CRMChatbotAgent(api_key=api_key, event_bus=self.event_bus, model=model)
        self.sales_closing_agent = SalesClosingAgent(api_key=api_key, event_bus=self.event_bus, model=model)

        self.event_bus.subscribe(CAR_ACQUIRED, self._on_car_acquired)
        self.event_bus.subscribe(PUBLISHED, self._on_published)
        self.event_bus.subscribe(LEAD_QUALIFIED, self._on_lead_qualified)
        self.event_bus.subscribe(SALE_COMPLETED, self._on_sale_completed)

    def _ts(self) -> str:
        return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def _on_car_acquired(self, event: Event) -> None:
        state_data = event.payload.get("state")
        if not isinstance(state_data, dict):
            return
        try:
            state = CarSaleState.model_validate(state_data)
        except Exception:
            return
        asyncio.create_task(self.publication_agent.generate_listing(state))

    def _on_published(self, event: Event) -> None:
        state = event.payload.get("state") or {}
        car_id = state.get("car_id")
        self.console.print(f"[green]{self._ts()}[/green] Publicado: {car_id}")

    def _on_lead_qualified(self, event: Event) -> None:
        state = event.payload.get("state") or {}
        car_id = state.get("car_id")
        self.console.print(f"[green]{self._ts()}[/green] Lead calificado para: {car_id}")

    def _on_sale_completed(self, event: Event) -> None:
        state = event.payload.get("state") or {}
        car_id = state.get("car_id")
        self.console.print(f"[green]{self._ts()}[/green] Venta completada: {car_id}")

    async def run_acquisition(self, car_data: dict[str, Any], inspection_data: dict[str, Any] = None) -> CarSaleState:
        self.console.print(f"[yellow]{self._ts()}[/yellow] Adquisición: iniciando análisis")
        state = await self.acquisition_agent.analyze_car(car_data=car_data, inspection_data=inspection_data)
        if state.car_data.get("apto_venta"):
            self.console.print(f"[green]{self._ts()}[/green] Auto apto. Publicación: generando anuncio")
            state = await self.publication_agent.generate_listing(state)
        else:
            self.console.print(f"[red]{self._ts()}[/red] Auto rechazado")
        return state

    async def run_crm(self, message: str, state: CarSaleState) -> dict[str, Any]:
        self.console.print(f"[yellow]{self._ts()}[/yellow] CRM: mensaje recibido")
        return await self.crm_chatbot_agent.handle_message(message=message, state=state)

    async def run_closing(self, offer: float, state: CarSaleState) -> dict[str, Any]:
        self.console.print(f"[yellow]{self._ts()}[/yellow] Cierre: negociando")
        return await self.sales_closing_agent.negotiate(offer=offer, state=state)

    async def run_full_pipeline(
        self,
        car_data: dict[str, Any],
        inspection_data: dict[str, Any],
        client_messages: list[str],
        final_offer: float,
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        state = await self.run_acquisition(car_data=car_data, inspection_data=inspection_data)

        if state.status == "rejected":
            total = (datetime.now(timezone.utc) - started).total_seconds()
            self.console.print(f"[red]{self._ts()}[/red] Pipeline terminado (rechazado)")
            summary = state.to_summary()
            summary["tiempo_total_s"] = total
            return summary

        for msg in client_messages:
            reply = await self.run_crm(message=msg, state=state)
            if reply.get("lead_calificado"):
                self.console.print(f"[green]{self._ts()}[/green] Lead calificado: listo para cierre")
                break

        closing = await self.run_closing(offer=final_offer, state=state)
        total = (datetime.now(timezone.utc) - started).total_seconds()

        color = "green" if state.status == "sold" else "yellow"
        self.console.print(f"[{color}]{self._ts()}[/{color}] Pipeline terminado: {state.status}")

        summary = state.to_summary()
        summary["tiempo_total_s"] = total
        summary["closing"] = closing
        return summary
