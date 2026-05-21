from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from groq import AsyncGroq

from shared.event_bus import EventBus, NEGOTIATION_FAILED, SALE_COMPLETED, new_event
from shared.state import CarSaleState
from tools.document_generator import generate_contract_pdf


SYSTEM_PROMPT = """Eres el Agente de Cierre de Venta de un sistema de venta de autos usados. Tu rol es:
1. Gestionar la negociación final del precio
2. Evaluar si una oferta del cliente es aceptable (mínimo: precio_mercado * 0.85)
3. Generar el resumen del contrato de compraventa con todos los datos necesarios
4. Registrar el resultado final: venta completada o negociación fallida
Responde SIEMPRE en JSON:
{
  "oferta_aceptable": boolean,
  "precio_final": number,
  "contraoferta": number (solo si oferta_aceptable es false),
  "resumen_contrato": {
    "vendedor": string,
    "comprador": string,
    "vehiculo": string,
    "precio": number,
    "forma_pago": string,
    "fecha": string,
    "clausulas": list[string]
  },
  "mensaje_cliente": string,
  "venta_completada": boolean
}"""


class SalesClosingAgent:
    def __init__(self, api_key: str, event_bus: EventBus, model: str = "llama-3.3-70b-versatile") -> None:
        self.client = AsyncGroq(api_key=api_key)
        self.event_bus = event_bus
        self.model = model

    async def negotiate(self, offer: float, state: CarSaleState) -> dict[str, Any]:
        offer = float(offer)
        precio_mercado = float(state.car_data.get("precio_mercado") or 0.0)
        min_aceptable = precio_mercado * 0.85 if precio_mercado > 0 else 0.0

        user_content = json.dumps(
            {
                "car_id": state.car_id,
                "offer": offer,
                "precio_mercado": precio_mercado,
                "min_aceptable": min_aceptable,
                "attempt": state.negotiation_attempts + 1,
                "car_data": state.car_data,
                "lead_data": state.lead_data,
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
            state.sale_data["error"] = f"No se pudo obtener JSON válido de Groq: {last_error}"
            return {"error": f"No se pudo obtener JSON válido de Groq: {last_error}", "venta_completada": False}

        oferta_aceptable = offer >= min_aceptable if min_aceptable > 0 else bool(parsed.get("oferta_aceptable"))
        parsed["oferta_aceptable"] = oferta_aceptable

        state.status = "negotiating"
        state.negotiation_attempts += 1

        if oferta_aceptable:
            precio_final = float(parsed.get("precio_final") or offer)
            resumen = parsed.get("resumen_contrato") or {}
            if isinstance(resumen, dict):
                resumen.setdefault(
                    "vehiculo",
                    f"{state.car_data.get('marca','')} {state.car_data.get('modelo','')} {state.car_data.get('año') or state.car_data.get('anio')}",
                )
                resumen.setdefault("precio", precio_final)
                resumen.setdefault("fecha", datetime.now(timezone.utc).date().isoformat())
                parsed["resumen_contrato"] = resumen

            pdf_path = generate_contract_pdf(
                output_path=f"contracts/{state.car_id}.pdf",
                contract=resumen if isinstance(resumen, dict) else {},
            )

            state.sale_data = {
                "precio_final": precio_final,
                "forma_pago": (resumen.get("forma_pago") if isinstance(resumen, dict) else None),
                "contrato_generado": True,
                "venta_completada": True,
                "contrato_pdf": pdf_path,
            }
            state.status = "sold"
            state.add_event(SALE_COMPLETED)
            self.event_bus.publish(
                new_event(SALE_COMPLETED, payload={"state": state.model_dump(), "result": parsed}, source_agent="closing")
            )
            parsed["venta_completada"] = True
            return parsed

        contraoferta = float(parsed.get("contraoferta") or max(min_aceptable, offer))
        parsed["contraoferta"] = contraoferta
        parsed["venta_completada"] = False

        if state.negotiation_attempts >= 3:
            state.sale_data = {
                "precio_final": None,
                "forma_pago": None,
                "contrato_generado": False,
                "venta_completada": False,
            }
            state.add_event(NEGOTIATION_FAILED)
            self.event_bus.publish(
                new_event(
                    NEGOTIATION_FAILED,
                    payload={"state": state.model_dump(), "result": parsed},
                    source_agent="closing",
                )
            )

        return parsed

    async def _call_groq(self, system_prompt: str, user_content: str) -> str:
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
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
