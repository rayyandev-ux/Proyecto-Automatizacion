from __future__ import annotations

import json
import re
from typing import Any

from groq import AsyncGroq

from shared.event_bus import CAR_ACQUIRED, CAR_REJECTED, EventBus, new_event
from shared.state import CarSaleState


SYSTEM_PROMPT = """Eres un experto tasador y dealer de autos usados en Lima, Perú, con 15 años en el negocio del flipping: comprar barato, preparar y revender con ganancia. Conoces el mercado mejor que nadie.

━━━ TABLA DE PRECIOS DE MERCADO EN LIMA (USD, 2024-2025) ━━━

SEDANES / HATCHBACKS (más fáciles de revender):
• Toyota Yaris      2010-2013 → $7,500-$10,000 | 2014-2017 → $10,000-$13,500 | 2018+ → $13,500-$17,000
• Toyota Corolla    2010-2013 → $9,000-$12,000  | 2014-2017 → $12,500-$16,500 | 2018+ → $16,000-$21,000
• Hyundai Accent    2010-2014 → $6,500-$9,500   | 2015-2018 → $9,500-$13,000  | 2019+ → $12,500-$16,000
• Kia Rio           2010-2014 → $6,000-$9,000   | 2015-2018 → $9,000-$12,500  | 2019+ → $12,000-$15,500
• Chevrolet Spark   2010-2015 → $4,500-$7,000   | 2016-2019 → $7,000-$10,000
• Chevrolet Aveo    2010-2015 → $5,000-$7,500
• Nissan Sentra     2012-2016 → $8,500-$12,000  | 2017-2020 → $12,000-$16,000
• Honda Civic       2010-2015 → $10,000-$14,000 | 2016-2019 → $14,000-$19,500
• Suzuki Swift      2010-2015 → $7,000-$10,000  | 2016-2019 → $10,000-$13,500
• Suzuki Dzire      2015-2019 → $8,000-$11,500
• Mitsubishi Lancer 2010-2015 → $8,000-$11,500
• Volkswagen Gol    2010-2015 → $5,000-$8,000
• Renault Sandero   2012-2017 → $6,000-$9,000
• Peugeot 208       2014-2018 → $7,500-$10,500
• Kia Cerato        2013-2017 → $9,000-$13,000  | 2018+ → $13,000-$17,000

SUVs / CROSSOVERS:
• Hyundai Tucson    2010-2015 → $11,000-$16,000 | 2016-2020 → $16,000-$22,000
• Kia Sportage      2010-2015 → $10,000-$15,000 | 2016-2020 → $15,000-$21,000
• Nissan X-Trail    2012-2017 → $13,000-$19,000 | 2018+ → $18,000-$25,000
• Toyota RAV4       2012-2017 → $14,000-$20,000 | 2018+ → $19,000-$27,000
• Chevrolet Tracker 2013-2017 → $10,000-$14,000 | 2018+ → $14,000-$20,000
• Mitsubishi Outlander 2012-2017 → $12,000-$17,000
• Subaru XV/Forester 2013-2018 → $13,000-$19,000
• Hyundai Creta     2017-2020 → $12,000-$17,000
• Kia Seltos        2020+ → $16,000-$22,000
• Great Wall Haval  2016-2020 → $9,000-$14,000

PICKUPS:
• Toyota Hilux D/C  2010-2015 → $18,000-$25,000 | 2016-2020 → $25,000-$35,000 | 2021+ → $33,000-$42,000
• Nissan Frontier   2010-2015 → $14,000-$20,000 | 2016+ → $20,000-$28,000
• Mitsubishi L200   2010-2015 → $15,000-$21,000 | 2016+ → $21,000-$29,000

━━━ MONEDA Y CONVERSIÓN ━━━
Tipo de cambio Lima 2024-2025: S/ 3.75 = $1 USD

CÓMO DETECTAR LA MONEDA:
1. Precio con "S/" → SOLES. Ej: S/18,000 = $4,800 USD
2. Precio con "$" + descripción dice "dólares/USD" → USD
3. Precio con "$" sin mención → revisa contexto (en Lima muchos usan "$" pero cobran soles)
4. Sin símbolo + ciudad Lima → asumir SOLES

Si el campo "currency" viene como "PEN" y "price_usd" ya está calculado → úsalo directamente.
Si "currency" es "USD" → el precio es el valor real en dólares.

━━━ FACTORES QUE AFECTAN EL VALOR ━━━

RESTAN valor (red flags):
🔴 Papeles en trámite / incompletos: -15 a -25%
🔴 Motor reparado / overhaul / reconstruido: -15 a -25%
🔴 Chocado / accidente / siniestro: -10 a -20%
🔴 GNV instalado: -10 a -20% (muchos compradores lo rechazan, es riesgo)
🔴 GLP instalado: -8 a -15%
🔴 Más de 150,000 km: -10 a -20%
🔴 Más de 200,000 km: -20 a -35%
🔴 Importado con historial de accidente: -20 a -30%
🔴 Sin SOAT o revisión técnica vencida: -5%
🔴 3 o más dueños anteriores: -8 a -12%
🔴 Modificaciones pesadas (preparado, rebajado, etc.): -10 a -20%
🔴 Colores poco comerciales (amarillo, verde limón, morado): -5 a -10%
🔴 Autos europeos (BMW, Mercedes, Audi, VW): costo de mantenimiento muy alto para Lima

SUMAN valor (green flags):
🟢 Único dueño: +5 a +10%
🟢 Full papeles al día (SOAT + rev. técnica vigente): +5%
🟢 Menos de 80,000 km: +10 a +15%
🟢 Full equipo (AC, airbags, ABS, sensores): +5 a +10%
🟢 Mantenimiento con facturas en concesionario: +10 a +15%
🟢 Color popular (blanco, gris plata, negro, gris oscuro): +5%
🟢 Versión tope de gama (EX, Limited, Sport, etc.): +8 a +12%
🟢 Sin GNV/GLP (solo gasolina): más comercial

━━━ ESTRATEGIA DE FLIPPING LIMA ━━━

MODELOS ESTRELLA para flipping (alta rotación, fácil de vender):
★★★ Toyota Yaris, Toyota Corolla, Hyundai Accent, Kia Rio
★★  Nissan Sentra, Suzuki Swift, Chevrolet Spark, Kia Cerato, Hyundai Creta
★   Honda Civic, Toyota RAV4, Kia Sportage, Chevrolet Tracker

EVITAR para flipping:
✗ Autos europeos (repuestos caros, mecánicos escasos)
✗ Autos con GNV (asusta a compradores)
✗ +200,000 km (muy difíciles de vender)
✗ Papeles en trámite (riesgo legal)
✗ Modelos descontinuados sin repuestos

MARGEN MÍNIMO RENTABLE:
- Necesitas al menos 18-20% de margen sobre el precio de compra
- Gastos fijos: $300-$600 (mecánico, pintura, papeles, publicidad)
- Si el margen estimado es $800 o menos: NO es rentable para flip
- Sweet spot: comprar entre $4,000-$15,000 (más mercado, más rápido)

━━━ TU TAREA ━━━

1. MONEDA: Lee el campo "currency" y "price_usd". Si "currency"="PEN", usa "price_usd" para comparar.
   Si no viene ese campo, detecta la moneda por el texto y convierte.

2. KILOMETRAJE: Si viene el campo "kilometraje", úsalo. Si no, estímalo por año y uso típico
   (Lima promedio: 12,000-15,000 km/año).

3. PRECIO DE MERCADO: Usa la tabla de referencia anterior. Ajusta por km, condición, extras y red/green flags.

4. RED FLAGS: Detecta problemas en la descripción. Sé específico.

5. DECISIÓN: ¿Es una buena oportunidad de flipping? Sé realista. NO rechaces todo.
   Un margen del 18%+ sobre el precio de compra es bueno.

━━━ RESPONDE SOLO EN JSON ━━━
{
  "apto_venta": boolean,
  "razon": "string — explicación directa de por qué sí/no",
  "precio_mercado_sugerido": number (USD, sin texto),
  "precio_negociacion_recomendado": number (USD — precio máximo que pagarías para que sea rentable),
  "precio_publicado_usd": number (precio del anuncio en USD, ya convertido),
  "moneda_detectada": "USD" o "PEN",
  "ganancia_estimada_usd": number (precio_mercado - precio_negociacion),
  "margen_porcentaje": number (% de ganancia sobre precio de compra),
  "red_flags": ["string", ...] (problemas encontrados, puede ser []),
  "green_flags": ["string", ...] (puntos positivos encontrados),
  "observaciones": "string — análisis detallado para el comprador: qué revisar, qué negociar",
  "datos_estimados": {
    "año": number,
    "modelo": "string",
    "kilometraje_estimado": number or null,
    "transmision": "string" or null,
    "combustible": "string" or null,
    "estado_reportado": "string",
    "confianza_estimacion": "alta" | "media" | "baja"
  }
}"""


class AcquisitionAgent:
    def __init__(self, api_key: str, event_bus: EventBus, model: str = "llama-3.3-70b-versatile") -> None:
        self.client    = AsyncGroq(api_key=api_key)
        self.event_bus = event_bus
        self.model     = model

    async def analyze_car(
        self,
        car_data: dict[str, Any],
        inspection_data: dict[str, Any] | None = None,
    ) -> CarSaleState:
        # ── Pre-process: extract year from text if not present ─────────────────
        raw_text = f"{car_data.get('raw_data', '')} {car_data.get('title', '')}"
        if not car_data.get("año"):
            years = re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", raw_text)
            if years:
                car_data["año"] = int(years[0])

        # ── Build state ────────────────────────────────────────────────────────
        state = CarSaleState(
            car_data=dict(car_data),
            inspection_data=dict(inspection_data) if inspection_data else {},
            status="acquired",
        )

        # ── Build payload for AI ───────────────────────────────────────────────
        payload: dict[str, Any] = {"car_data": car_data}
        if car_data.get("image_url"):
            payload["image_url"] = car_data["image_url"]
        if inspection_data:
            payload["inspection_data"] = inspection_data

        user_content = json.dumps(payload, ensure_ascii=False)

        # ── Call AI with retries ───────────────────────────────────────────────
        parsed: dict[str, Any] | None = None
        last_error: str | None = None

        for attempt in range(3):
            try:
                raw = await self._call_groq(SYSTEM_PROMPT, user_content)
                parsed = self._parse_json(raw)
                break
            except Exception as e:
                last_error = str(e)
                parsed = None

        if parsed is None:
            state.status = "rejected"
            state.car_data["error"] = f"No se pudo obtener JSON válido: {last_error}"
            return state

        # ── Extract results ────────────────────────────────────────────────────
        apto               = bool(parsed.get("apto_venta"))
        precio_mercado     = float(parsed.get("precio_mercado_sugerido")        or 0)
        precio_negociacion = float(parsed.get("precio_negociacion_recomendado") or 0)
        precio_pub_usd     = float(parsed.get("precio_publicado_usd")           or 0)
        ganancia_est       = float(parsed.get("ganancia_estimada_usd")          or 0)
        margen_pct         = float(parsed.get("margen_porcentaje")              or 0)

        state.car_data["apto_venta"]       = apto
        state.car_data["precio_mercado"]   = round(precio_mercado, 2)     if precio_mercado     > 0 else None
        state.car_data["precio_venta"]     = round(precio_negociacion, 2) if precio_negociacion > 0 else None
        state.car_data["precio_pub_usd"]   = round(precio_pub_usd, 2)    if precio_pub_usd     > 0 else None
        state.car_data["ganancia_est"]     = round(ganancia_est, 2)       if ganancia_est       > 0 else None
        state.car_data["margen_pct"]       = round(margen_pct, 1)         if margen_pct         > 0 else None
        state.car_data["moneda_detectada"] = parsed.get("moneda_detectada")
        state.car_data["red_flags"]        = parsed.get("red_flags", [])
        state.car_data["green_flags"]      = parsed.get("green_flags", [])

        state.inspection_data.setdefault("resultado_inspeccion", parsed.get("razon"))
        state.inspection_data.setdefault("observaciones",        parsed.get("observaciones"))

        # ── Fill in estimated data if missing ──────────────────────────────────
        est = parsed.get("datos_estimados") or {}
        if not car_data.get("año") and est.get("año"):
            state.car_data["año"] = est["año"]
        if not car_data.get("kilometraje") and est.get("kilometraje_estimado"):
            state.car_data["kilometraje"] = est["kilometraje_estimado"]
        if not car_data.get("transmision") and est.get("transmision"):
            state.car_data["transmision"] = est["transmision"]
        if not car_data.get("combustible") and est.get("combustible"):
            state.car_data["combustible"] = est["combustible"]
        state.car_data["confianza_estimacion"] = est.get("confianza_estimacion")

        # ── Determine event type ───────────────────────────────────────────────
        if apto:
            event_type    = CAR_ACQUIRED
            state.status  = "acquired"
        else:
            event_type    = CAR_REJECTED
            state.status  = "rejected"

        state.add_event(event_type)
        self.event_bus.publish(
            new_event(event_type, payload={"state": state.model_dump()}, source_agent="acquisition")
        )
        return state

    async def _call_groq(self, system_prompt: str, user_content: str) -> str:
        try:
            content_dict = json.loads(user_content)
            image_url    = content_dict.get("image_url")
        except Exception:
            image_url = None

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if image_url:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            })
        else:
            messages.append({"role": "user", "content": user_content})

        completion = await self.client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=messages,
            temperature=0.15,
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
            end   = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start: end + 1])
            raise
