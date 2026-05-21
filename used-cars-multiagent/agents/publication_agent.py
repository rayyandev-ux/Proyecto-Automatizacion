from __future__ import annotations

import json
from typing import Any

from groq import AsyncGroq

from shared.event_bus import EventBus, PUBLISHED, new_event
from shared.state import CarSaleState
from tools.listing_publisher import build_mock_urls


SYSTEM_PROMPT = """Eres el Agente de Publicación de un sistema de venta de autos usados. Tu rol es:
1. Generar descripciones atractivas y verídicas para anuncios de autos usados
2. Adaptar el tono según la plataforma: Facebook Marketplace (casual), MercadoLibre (técnico y detallado), Instagram (corto e impactante)
3. Destacar las mejores características del auto sin mentir
4. Incluir siempre: precio, año, km, características principales, estado del auto, forma de contacto
Responde SIEMPRE en JSON con esta estructura:
{
  "descripcion_facebook": string (max 500 chars),
  "descripcion_mercadolibre": string (max 1500 chars, incluye ficha técnica),
  "descripcion_instagram": string (max 200 chars + hashtags),
  "titulo_anuncio": string (max 80 chars),
  "precio_publicar": number,
  "tags_seo": list[string]
}"""


class PublicationAgent:
    def __init__(self, api_key: str, event_bus: EventBus, model: str = "llama-3.3-70b-versatile") -> None:
        self.client = AsyncGroq(api_key=api_key)
        self.event_bus = event_bus
        self.model = model

    async def generate_listing(self, state: CarSaleState) -> CarSaleState:
        user_content = json.dumps(
            {
                "car_id": state.car_id,
                "car_data": state.car_data,
                "inspection_data": state.inspection_data,
            },
            ensure_ascii=False,
        )

        parsed: dict[str, Any] | None = None
        last_error: Exception | None = None

        for _ in range(3):
            try:
                text = await self._call_groq(system_prompt=SYSTEM_PROMPT, user_content=user_content)
                parsed = self._parse_json(text)
                break
            except Exception as e:
                last_error = e
                parsed = None

        if parsed is None:
            state.publication_data = {"error": f"No se pudo obtener JSON válido de Groq: {last_error}"}
            state.status = "published"
            return state

        urls = build_mock_urls(state.car_id)

        state.publication_data = {
            "descripcion_generada": {
                "facebook": parsed.get("descripcion_facebook"),
                "mercadolibre": parsed.get("descripcion_mercadolibre"),
                "instagram": parsed.get("descripcion_instagram"),
            },
            "titulo_anuncio": parsed.get("titulo_anuncio"),
            "precio_publicar": parsed.get("precio_publicar"),
            "tags_seo": parsed.get("tags_seo") or [],
            "urls_publicadas": urls,
            "plataformas": ["facebook_marketplace", "mercadolibre", "instagram"],
        }

        state.status = "published"
        state.add_event(PUBLISHED)
        self.event_bus.publish(new_event(PUBLISHED, payload={"state": state.model_dump()}, source_agent="publication"))
        return state

    async def _call_groq(self, system_prompt: str, user_content: str) -> str:
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        return completion.choices[0].message.content

    def _parse_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise
