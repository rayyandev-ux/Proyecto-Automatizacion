from __future__ import annotations

import json
from typing import Any

from groq import AsyncGroq

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
    def __init__(self, api_key: str, event_bus: EventBus, model: str = "llama-3.3-70b-versatile") -> None:
        self.client = AsyncGroq(api_key=api_key)
        self.event_bus = event_bus
        self.model = model

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
                text = await self._call_groq(system_prompt=SYSTEM_PROMPT, user_content=user_content)
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
            event_type = LEAD_DISCARDED
            state.lead_data["motivo_descarte"] = parsed.get("motivo_descarte")

        state.add_event(event_type)
        self.event_bus.publish(new_event(event_type, payload={"state": state.model_dump()}, source_agent="crm"))

        return parsed

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
