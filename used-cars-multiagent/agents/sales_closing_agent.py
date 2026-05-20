from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

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
    model = "gemini-2.5-flash"

    def __init__(self, api_key: str, event_bus: EventBus) -> None:
        self.api_key = api_key
        self.event_bus = event_bus

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
                text = await self._call_gemini(system_prompt=SYSTEM_PROMPT, user_content=user_content)
                parsed = self._parse_json(text)
                break
            except Exception as e:
                last_error = e
                parsed = None

        if parsed is None:
            state.sale_data["error"] = f"No se pudo obtener JSON válido del LLM: {last_error}"
            return {"error": f"No se pudo obtener JSON válido del LLM: {last_error}", "venta_completada": False}

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

    async def _call_gemini(self, system_prompt: str, user_content: str) -> str:
        if not self.api_key:
            raise ValueError("Falta GOOGLE_API_KEY (api_key) para llamar a Gemini")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "temperature": 0.3,
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
