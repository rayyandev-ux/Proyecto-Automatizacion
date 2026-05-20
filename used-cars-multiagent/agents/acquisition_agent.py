from __future__ import annotations

import json
from typing import Any

import httpx

from shared.event_bus import CAR_ACQUIRED, CAR_REJECTED, EventBus, new_event
from shared.state import CarSaleState


SYSTEM_PROMPT = """Eres el Agente de Adquisición de un sistema experto en "Flipping" de autos usados (comprar barato, vender caro). Tu rol es:
1. Analizar datos de un auto extraído de Facebook Marketplace.
2. Estimar el precio de mercado real basado en marca, modelo, año y características.
3. Evaluar si el auto es una "Buena Oferta" (apto_venta = true) si el precio publicado está al menos 15-20% por debajo del precio de mercado estimado.
4. Eres flexible con el margen de ganancia: si consideras que es una buena oportunidad de compra (flipping), un modelo muy comercial, o simplemente está barato, evalúa 'apto_venta': true. No te apegues estrictamente a un porcentaje si ves potencial.
5. Redactar las razones por las que es una buena oferta (o por qué se rechaza).
Responde SIEMPRE en JSON con esta estructura exacta:
{
  "apto_venta": boolean,
  "razon": string,
  "precio_mercado_sugerido": number (en USD),
  "precio_negociacion_recomendado": number (en USD, 15% menos que mercado),
  "observaciones": string
}"""


class AcquisitionAgent:
    model = "gemini-2.5-flash"

    def __init__(self, api_key: str, event_bus: EventBus) -> None:
        self.api_key = api_key
        self.event_bus = event_bus

    async def analyze_car(self, car_data: dict[str, Any], inspection_data: dict[str, Any] | None = None) -> CarSaleState:
        year_from_title = None
        raw_text = car_data.get("raw_data", "") + " " + car_data.get("title", "")
        import re
        years = re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", raw_text)
        if years:
            year_from_title = int(years[0])

        car_data["año"] = car_data.get("año") or car_data.get("anio") or year_from_title

        if car_data.get("año") is None:
            raise ValueError("car_data incompleto: falta año/anio")

        state = CarSaleState(
            car_data=dict(car_data),
            inspection_data=dict(inspection_data) if inspection_data else {},
            status="acquired",
        )

        payload_dict = {"car_data": car_data}
        if inspection_data:
            payload_dict["inspection_data"] = inspection_data

        user_content = json.dumps(
            payload_dict,
            ensure_ascii=False,
        )

        parsed: dict[str, Any] | None = None
        last_error: str | None = None
        raw_text = ""

        for _ in range(3):
            try:
                raw_text = await self._call_gemini(system_prompt=SYSTEM_PROMPT, user_content=user_content)
                parsed = self._parse_json(raw_text)
                break
            except Exception as e:
                last_error = f"{e}. RAW OUTPUT: {raw_text[:500]}" if raw_text else str(e)
                parsed = None

        if parsed is None:
            state.status = "rejected"
            state.car_data["error"] = f"No se pudo obtener JSON válido del LLM: {last_error}"
            return state

        apto = bool(parsed.get("apto_venta"))
        precio_mercado = float(parsed.get("precio_mercado_sugerido") or 0.0)
        precio_negociacion = float(parsed.get("precio_negociacion_recomendado") or 0.0)

        state.car_data["apto_venta"] = apto
        state.car_data["precio_mercado"] = round(precio_mercado, 2) if precio_mercado > 0 else None
        state.car_data["precio_venta"] = round(precio_negociacion, 2) if precio_negociacion > 0 else None
        state.inspection_data.setdefault("resultado_inspeccion", parsed.get("razon"))
        state.inspection_data.setdefault("observaciones", parsed.get("observaciones"))

        if apto:
            event_type = CAR_ACQUIRED
            state.status = "acquired"
        else:
            # Fallback en caso de que Gemini se equivoque en el booleano pero la descripcion diga que es buena oferta
            razon_str = str(parsed.get("razon", "")).lower() + str(parsed.get("observaciones", "")).lower()
            if "excelente oportunidad" in razon_str or "margen" in razon_str and "ganancia" in razon_str:
                event_type = CAR_ACQUIRED
                state.status = "acquired"
                state.car_data["apto_venta"] = True
            else:
                event_type = CAR_REJECTED
                state.status = "rejected"

        state.add_event(event_type)
        self.event_bus.publish(new_event(event_type, payload={"state": state.model_dump()}, source_agent="acquisition"))
        return state

    async def _call_gemini(self, system_prompt: str, user_content: str) -> str:
        if not self.api_key:
            raise ValueError("Falta GOOGLE_API_KEY (api_key) para llamar a Gemini")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()

        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError(f"Respuesta vacía del modelo: {json.dumps(data, ensure_ascii=False)[:600]}")

        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        text = "\n".join(part for part in text_parts if part).strip()
        if not text:
            raise ValueError(f"No se encontró texto en la respuesta: {json.dumps(data, ensure_ascii=False)[:600]}")
        
        import logging
        logging.warning(f"=== RAW GEMINI OUTPUT ===\n{text}\n=====================")
        return text

    def _parse_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json\n", "", 1).strip()
        if not text:
            raise ValueError("Respuesta vacía o no textual del modelo")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(text[start : end + 1])
