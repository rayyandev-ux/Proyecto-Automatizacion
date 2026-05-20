import json
from unittest.mock import AsyncMock

import pytest

from agents.publication_agent import PublicationAgent
from shared.event_bus import EventBus
from shared.state import CarSaleState


@pytest.mark.asyncio
async def test_description_generated():
    bus = EventBus()
    agent = PublicationAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "descripcion_facebook": "FB",
                "descripcion_mercadolibre": "ML",
                "descripcion_instagram": "IG #auto",
                "titulo_anuncio": "Toyota Corolla 2019",
                "precio_publicar": 12500,
                "tags_seo": ["toyota", "corolla"],
            }
        )
    )

    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000, "precio_venta": 11900},
        inspection_data={"score_fisico": 82},
    )
    out = await agent.generate_listing(state)
    desc = out.publication_data["descripcion_generada"]
    assert desc["facebook"]
    assert desc["mercadolibre"]
    assert desc["instagram"]


@pytest.mark.asyncio
async def test_urls_generated():
    bus = EventBus()
    agent = PublicationAgent(api_key="test", event_bus=bus)
    agent._call_gemini = AsyncMock(
        return_value=json.dumps(
            {
                "descripcion_facebook": "FB",
                "descripcion_mercadolibre": "ML",
                "descripcion_instagram": "IG",
                "titulo_anuncio": "Anuncio",
                "precio_publicar": 12000,
                "tags_seo": [],
            }
        )
    )

    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "km": 45000, "precio_venta": 11900},
        inspection_data={"score_fisico": 82},
    )
    out = await agent.generate_listing(state)
    urls = out.publication_data.get("urls_publicadas")
    assert isinstance(urls, list)
    assert len(urls) == 3
