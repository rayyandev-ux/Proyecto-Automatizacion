import json
from unittest.mock import AsyncMock

import pytest

from agents.acquisition_agent import AcquisitionAgent
from agents.orchestrator import Orchestrator
from agents.sales_closing_agent import SalesClosingAgent
from agents.crm_chatbot_agent import CRMChatbotAgent
from shared.event_bus import EventBus, NEGOTIATION_FAILED
from shared.state import CarSaleState


@pytest.mark.asyncio
async def test_negotiation_max_attempts():
    bus = EventBus()
    agent = SalesClosingAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "oferta_aceptable": False,
                "precio_final": 0,
                "contraoferta": 12000,
                "resumen_contrato": {"vendedor": "X", "comprador": "Y", "vehiculo": "Z", "precio": 0, "forma_pago": "cash", "fecha": "2026-05-20", "clausulas": []},
                "mensaje_cliente": "No",
                "venta_completada": False,
            }
        )
    )

    state = CarSaleState(car_data={"precio_mercado": 14000, "marca": "Toyota", "modelo": "Corolla", "año": 2019})
    await agent.negotiate(offer=5000, state=state)
    await agent.negotiate(offer=6000, state=state)
    await agent.negotiate(offer=7000, state=state)
    assert state.negotiation_attempts == 3
    assert NEGOTIATION_FAILED in state.events


@pytest.mark.asyncio
async def test_car_border_score():
    bus = EventBus()
    agent = AcquisitionAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "apto_venta": True,
                "razon": "Score en límite",
                "precio_mercado_sugerido": 12000,
                "precio_negociacion_recomendado": 10200,
                "observaciones": "OK",
            }
        )
    )
    state = await agent.analyze_car(
        car_data={"marca": "Honda", "modelo": "Civic", "año": 2017, "km": 98000, "color": "Azul"},
        inspection_data={"defectos_encontrados": [], "score_fisico": 60},
    )
    assert state.car_data["apto_venta"] is True


@pytest.mark.asyncio
async def test_invalid_car_data():
    bus = EventBus()
    agent = AcquisitionAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(return_value="{}")
    with pytest.raises(ValueError):
        await agent.analyze_car(
            car_data={"marca": "Toyota", "modelo": "Corolla", "km": 45000},
            inspection_data={"defectos_encontrados": [], "score_fisico": 82},
        )


@pytest.mark.asyncio
async def test_empty_client_message():
    bus = EventBus()
    agent = CRMChatbotAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "respuesta_cliente": "Hola, ¿en qué puedo ayudarte?",
                "lead_calificado": False,
                "motivo_descarte": "",
                "siguiente_accion": "seguir_conversacion",
                "resumen_intencion": "saludo",
            }
        )
    )
    state = CarSaleState(car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000})
    out = await agent.handle_message("", state)
    assert "respuesta_cliente" in out


@pytest.mark.asyncio
async def test_full_pipeline_rejection(monkeypatch):
    orch = Orchestrator(api_key="test")

    async def mocked_analyze_car(car_data, inspection_data):
        state = CarSaleState(car_data=car_data, inspection_data=inspection_data, status="rejected")
        state.car_data["apto_venta"] = False
        return state

    monkeypatch.setattr(orch.acquisition_agent, "analyze_car", mocked_analyze_car)

    summary = await orch.run_full_pipeline(
        car_data={"marca": "Ford", "modelo": "F-150", "año": 2012, "km": 215000},
        inspection_data={"defectos_encontrados": ["Motor con ruido"], "score_fisico": 38},
        client_messages=["¿Está disponible?"],
        final_offer=3000,
    )
    assert summary["status"] == "rejected"
