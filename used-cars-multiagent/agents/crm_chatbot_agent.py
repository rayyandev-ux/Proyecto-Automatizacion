from __future__ import annotations

import json
from typing import Any

import httpx

from shared.event_bus import EventBus, LEAD_DISCARDED, LEAD_QUALIFIED, new_event
from shared.state import CarSaleState


SYSTEM_PROMPT = """Eres el Agente CRM de un sistema de venta de autos usados. Tu rol es:
1. Responder preguntas de clientes potenciales sobre el auto de forma amable y profesional
2. Calificar leads: un lead está calificado si muestra intención real de compra (pregunta por precio final, quiere ver el auto, pregunta por financiamiento o formas de pago)
3. Detectar leads no interesados: solo curiosidad, precios muy bajos irreales, o respuestas evasivas
4. Registrar el motivo de descarte si el lead no califica (para análisis futuro)
Responde SIEMPRE en JSON:
{
  "respuesta_cliente": string (respuesta amable al cliente),
  "lead_calificado": boolean,
  "motivo_descarte": string (solo si lead_calificado es false),
  "siguiente_accion": string ("agendar_cita" | "seguir_conversacion" | "descartar"),
  "resumen_intencion": string
}"""


class CRMChatbotAgent:
    model = "gemini-2.5-flash"

    def __init__(self, api_key: str, event_bus: EventBus) -> None:
        self.api_key = api_key
        self.event_bus = event_bus

    async def handle_message(self, message: str, state: CarSaleState) -> dict[str, Any]:
        message = (message or "").strip()

        consultas = state.lead_data.get("consultas")
        if not isinstance(consultas, list):
            consultas = []

        consultas.append(message)
        state.lead_data["consultas"] = consultas

        user_content = json.dumps(
            {
                "car_id": state.car_id,
                "car_data": state.car_data,
                "inspection_data": state.inspection_data,
                "historial": consultas,
            },
            ensure_ascii=False,
        )

        parsed: dict[str, Any] | None = None
        last_error: Exception | None = None

        for _ in range(3):
            try:
                text = await self._call_gemini(system_prompt=SYSTEM_PROMPT, user_content=user_content)
                parsed = self._parse_json(text)
                break
            except Exception as e:
                last_error = e
                parsed = None

        if parsed is None:
            parsed = {
                "respuesta_cliente": "¿Podrías detallar tu consulta? Estoy para ayudarte.",
                "lead_calificado": False,
                "motivo_descarte": "respuesta_llm_invalida",
                "siguiente_accion": "seguir_conversacion",
                "resumen_intencion": "sin_respuesta_llm",
                "error": str(last_error),
            }

        lead_calificado = bool(parsed.get("lead_calificado"))
        state.lead_data["lead_calificado"] = lead_calificado

        if lead_calificado:
            event_type = LEAD_QUALIFIED
        else:
            event_type = LEAD_DISCARDED if parsed.get("siguiente_accion") == "descartar" else LEAD_DISCARDED
            state.lead_data["motivo_descarte"] = parsed.get("motivo_descarte")

        state.add_event(event_type)
        self.event_bus.publish(new_event(event_type, payload={"state": state.model_dump()}, source_agent="crm"))

        return parsed

    async def _call_gemini(self, system_prompt: str, user_content: str) -> str:
        if not self.api_key:
            raise ValueError("Falta GOOGLE_API_KEY (api_key) para llamar a Gemini")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "temperature": 0.4,
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
