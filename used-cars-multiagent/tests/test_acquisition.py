import json
from unittest.mock import AsyncMock

import pytest

from agents.acquisition_agent import AcquisitionAgent
from shared.event_bus import EventBus


@pytest.mark.asyncio
async def test_car_approved():
    bus = EventBus()
    agent = AcquisitionAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "apto_venta": True,
                "razon": "Cumple criterios",
                "precio_mercado_sugerido": 14000,
                "precio_negociacion_recomendado": 11900,
                "observaciones": "OK",
            }
        )
    )

    state = await agent.analyze_car(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000, "color": "Blanco"},
        inspection_data={"defectos_encontrados": [], "score_fisico": 82},
    )
    assert state.car_data["apto_venta"] is True


@pytest.mark.asyncio
async def test_car_rejected_km():
    bus = EventBus()
    agent = AcquisitionAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "apto_venta": False,
                "razon": "Km excesivo",
                "precio_mercado_sugerido": 8000,
                "precio_negociacion_recomendado": 6800,
                "observaciones": "No apto",
            }
        )
    )

    state = await agent.analyze_car(
        car_data={"marca": "Ford", "modelo": "F-150", "año": 2012, "km": 215000, "color": "Gris"},
        inspection_data={"defectos_encontrados": ["Motor con ruido"], "score_fisico": 38},
    )
    assert state.car_data["apto_venta"] is False
    assert state.status == "rejected"


@pytest.mark.asyncio
async def test_price_suggestion():
    bus = EventBus()
    agent = AcquisitionAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "apto_venta": True,
                "razon": "OK",
                "precio_mercado_sugerido": 10000,
                "precio_negociacion_recomendado": 8500,
                "observaciones": "OK",
            }
        )
    )

    state = await agent.analyze_car(
        car_data={"marca": "Honda", "modelo": "Civic", "año": 2017, "km": 98000, "color": "Azul"},
        inspection_data={"defectos_encontrados": [], "score_fisico": 61},
    )
    assert isinstance(state.car_data.get("precio_mercado"), (int, float))
    assert state.car_data["precio_mercado"] > 0
