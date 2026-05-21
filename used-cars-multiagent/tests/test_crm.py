import json
from unittest.mock import AsyncMock

import pytest

from agents.crm_chatbot_agent import CRMChatbotAgent
from shared.event_bus import EventBus
from shared.state import CarSaleState


@pytest.mark.asyncio
async def test_qualified_lead():
    bus = EventBus()
    agent = CRMChatbotAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "respuesta_cliente": "Claro, coordinemos.",
                "lead_calificado": True,
                "siguiente_accion": "agendar_cita",
                "resumen_intencion": "quiere ver el auto",
            }
        )
    )

    state = CarSaleState(car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000})
    out = await agent.handle_message("¿Cuánto es lo menos que acepta? Quiero ir a verlo mañana", state)
    assert out["lead_calificado"] is True


@pytest.mark.asyncio
async def test_unqualified_lead():
    bus = EventBus()
    agent = CRMChatbotAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "respuesta_cliente": "El precio es fijo por ahora.",
                "lead_calificado": False,
                "motivo_descarte": "oferta_irreal",
                "siguiente_accion": "seguir_conversacion",
                "resumen_intencion": "solo tiene 3000",
            }
        )
    )

    state = CarSaleState(car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000})
    out = await agent.handle_message("¿Puede ser más barato? Solo tengo 3000", state)
    assert out["lead_calificado"] is False


@pytest.mark.asyncio
async def test_conversation_history():
    bus = EventBus()
    agent = CRMChatbotAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "respuesta_cliente": "OK",
                "lead_calificado": False,
                "motivo_descarte": "",
                "siguiente_accion": "seguir_conversacion",
                "resumen_intencion": "pregunta",
            }
        )
    )

    state = CarSaleState(car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000})
    await agent.handle_message("¿Sigue disponible?", state)
    await agent.handle_message("¿Tiene financiamiento?", state)
    assert state.lead_data["consultas"] == ["¿Sigue disponible?", "¿Tiene financiamiento?"]
