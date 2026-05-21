"""Anymotor Telegram Bot Agent — conversational AI with full app access."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from datetime import datetime
from typing import Any

import requests
from groq import Groq

from agents.orchestrator import Orchestrator
from tools.airtable_tool import AirtableTool
from tools.seen_listings import is_seen, mark_seen

BOT_MODEL = "llama-3.3-70b-versatile"


# ── Logging helpers (defined early so all class methods can reference them) ───

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[AnyBot {ts}] {msg}", flush=True)


def _fmt_args(args: dict) -> str:
    """Compact one-liner of tool arguments for logging."""
    parts = []
    for k, v in args.items():
        v_str = str(v)
        parts.append(f"{k}={v_str[:30]!r}" if len(v_str) > 30 else f"{k}={v_str!r}")
    return ", ".join(parts)

SYSTEM_PROMPT = """Eres el agente inteligente de Anymotor, una herramienta de flipping de autos usados en Perú.
Ayudas al usuario a encontrar, analizar y gestionar autos para comprar y revender con ganancia.

CAPACIDADES:
- buscar_autos: busca y analiza autos en Facebook Marketplace (Lima, Trujillo, Arequipa)
- ver_pipeline: muestra los autos guardados por estado en la base de datos
- analizar_url: analiza un listing específico de Facebook Marketplace por URL
- actualizar_estado: cambia el estado de un deal en la base de datos
- resumen: estadísticas de ganancias y pipeline

CONTEXTO DEL MERCADO PERUANO:
- Tipo de cambio: S/3.75 = $1 USD
- Margen mínimo rentable: 18-20% sobre el precio de compra
- Sweet spot Lima: $4,000-$15,000
- Mejores modelos para flip: Toyota Yaris, Corolla, Hyundai Accent, Kia Rio, Suzuki Swift

REGLAS CRÍTICAS — DEBES SEGUIRLAS SIEMPRE:

1. CANTIDAD: `cantidad` = número de autos a analizar (1-5 máximo absoluto).
   - "busca 1 Hilux" → cantidad=1
   - "busca 3 autos" → cantidad=3
   - "busca 20 autos" → cantidad=5, informa al usuario del límite

2. PRECIO — regla más importante:
   - Si el usuario pide un MODELO ESPECÍFICO y NO menciona precio → omite precio_min y precio_max (deja en 0 = sin filtro). Ejemplo: "busca una Hilux en Trujillo" → precio_min=0, precio_max=0
   - Si el usuario busca SIN modelo específico → usa precio_min=3000, precio_max=15000
   - Si el usuario menciona un rango explícito ("menos de 10000", "entre 5k y 8k") → úsalo exactamente
   - Modelos caros que SIEMPRE van sin filtro de precio: Hilux, Land Cruiser, RAV4, Fortuner, Ranger, Frontier, L200, Outlander, Tucson, Sportage (pueden costar $15,000-$40,000)

3. NUNCA llames buscar_autos más de UNA vez por mensaje. Si ya buscaste, responde con lo que encontraste.

4. Si buscar_autos no encuentra resultados → responde al usuario directamente. NO busques de nuevo con otros parámetros.

4b. Si el usuario pide "lista los resultados", "muéstrame lo que encontraste" o similar → los resultados ya están en el historial de conversación anterior. NO vuelvas a llamar buscar_autos. Responde usando el historial.

5b. Cuando el usuario diga "acepta", "acepta todas", "acepta las oportunidades" → usa actualizar_estado con nuevo_estado="Contactando" para CADA auto encontrado. El titulo_parcial debe ser una parte EXACTA del título que apareció en los resultados anteriores (cópialo del historial). Puedes llamar actualizar_estado múltiples veces seguidas, una por auto.

5. Cuando el usuario pegue una URL de Facebook Marketplace → usa analizar_url.
6. Cuando pregunte por sus autos, pipeline o negociaciones → usa ver_pipeline UNA VEZ. Su resultado se envía directamente al usuario; no repitas la llamada.
7. Cuando pregunte por estadísticas o ganancias → usa resumen UNA VEZ. Su resultado se envía directamente al usuario; no repitas la llamada.
8. NUNCA encadenes varias herramientas en la misma respuesta a menos que el usuario lo pida explícitamente.
8b. Si el usuario pregunta por un auto ESPECÍFICO del pipeline que ya se mostró ("cuánto vale el Nissan Sentra", "dime más del Ford Explorer") → usa la información del historial de conversación para responder. NO llames ver_pipeline de nuevo.
9. Responde siempre en español, directo y conciso.
10. Usa emojis con moderación."""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "buscar_autos",
            "description": (
                "Busca y analiza autos en Facebook Marketplace de una ciudad peruana. "
                "Tarda 1-3 minutos. SOLO puede llamarse UNA VEZ por turno. "
                "El campo cantidad va de 1 a 5 (máximo absoluto). "
                "Si el usuario pide más de 5, usa 5 e informa el límite."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ciudad": {
                        "type": "string",
                        "enum": ["lima", "trujillo", "arequipa"],
                        "description": "Ciudad peruana donde buscar",
                    },
                    "modelo": {
                        "type": "string",
                        "description": "Modelo a buscar (ej: 'Toyota Corolla'). Vacío = cualquier auto.",
                    },
                    "precio_min": {
                        "type": "integer",
                        "description": (
                            "Precio mínimo en USD. USA 0 para buscar sin límite mínimo. "
                            "Omite o usa 0 cuando el usuario pide un modelo específico sin mencionar precio."
                        ),
                    },
                    "precio_max": {
                        "type": "integer",
                        "description": (
                            "Precio máximo en USD. USA 0 para buscar sin límite máximo. "
                            "Omite o usa 0 cuando el usuario pide un modelo específico sin mencionar precio. "
                            "Modelos caros (Hilux, RAV4, SUVs) suelen costar más de $15,000 — no les pongas límite."
                        ),
                    },
                    "cantidad": {"type": "integer", "description": "Autos a analizar, 1-5 (defecto: 3)"},
                },
                "required": ["ciudad"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ver_pipeline",
            "description": "Muestra los autos guardados en Airtable, opcionalmente filtrados por estado del pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "estado": {
                        "type": "string",
                        "enum": ["todos", "Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"],
                        "description": "Estado a filtrar. 'todos' para ver todos.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analizar_url",
            "description": "Analiza un auto específico a partir de su URL de Facebook Marketplace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL completa del listing de Facebook Marketplace"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_estado",
            "description": "Actualiza el estado del pipeline de un auto guardado en Airtable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo_parcial": {
                        "type": "string",
                        "description": "Parte del título del auto para identificarlo (ej: 'Corolla 2018')",
                    },
                    "nuevo_estado": {
                        "type": "string",
                        "enum": ["Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"],
                        "description": "Nuevo estado del pipeline",
                    },
                },
                "required": ["titulo_parcial", "nuevo_estado"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumen",
            "description": "Muestra estadísticas generales: autos por estado, ganancia potencial y real.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class TelegramBotAgent:
    """Long-polling Telegram bot backed by a Groq function-calling agent."""

    def __init__(
        self,
        token: str,
        groq_key: str,
        allowed_users: list[str] | None = None,
    ) -> None:
        self.token         = token
        self.groq_key      = groq_key
        self.allowed_users = [str(u).strip() for u in (allowed_users or []) if str(u).strip()]
        self.airtable      = AirtableTool()
        self.client        = Groq(api_key=groq_key)
        self._offset       = 0
        self._running      = False
        self._history: dict[int, list[dict]] = {}

    # ── Telegram API helpers ──────────────────────────────────────────────────

    def _post(self, method: str, **payload) -> dict:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/{method}",
                json=payload,
                timeout=10,
            )
            return r.json()
        except Exception:
            return {}

    def send_message(self, chat_id: int, text: str) -> None:
        """Sends text, splitting if over Telegram's 4096-char limit."""
        for chunk in _split_text(text, 4000):
            self._post("sendMessage", chat_id=chat_id, text=chunk, parse_mode="Markdown")

    def _typing(self, chat_id: int) -> None:
        self._post("sendChatAction", chat_id=chat_id, action="typing")

    def _get_updates(self) -> list[dict]:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"offset": self._offset, "timeout": 25},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("result", [])
        except Exception:
            pass
        return []

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _is_authorized(self, user_id: int) -> bool:
        if not self.allowed_users:
            return False
        return str(user_id) in self.allowed_users

    # ── Main polling loop ─────────────────────────────────────────────────────

    def run_forever(self) -> None:
        self._running = True
        print(f"[AnyBot] Iniciado. Usuarios autorizados: {self.allowed_users or 'ninguno'}")
        while self._running:
            try:
                for upd in self._get_updates():
                    self._offset = upd["update_id"] + 1
                    self._dispatch(upd)
            except Exception as e:
                print(f"[AnyBot] Error en polling: {e}")
                time.sleep(5)

    def _dispatch(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg or not msg.get("text"):
            return
        chat_id  = msg["chat"]["id"]
        user_id  = msg["from"]["id"]
        username = msg["from"].get("username") or msg["from"].get("first_name") or str(user_id)
        text     = msg["text"].strip()
        _log(f"MSG  [{username}] → {text[:120]}")
        threading.Thread(
            target=self._handle, args=(chat_id, user_id, username, text), daemon=True
        ).start()

    # ── Message handler ───────────────────────────────────────────────────────

    def _handle(self, chat_id: int, user_id: int, username: str, text: str) -> None:
        if not self._is_authorized(user_id):
            _log(f"DENY [{username}] id={user_id} — no autorizado")
            self.send_message(
                chat_id,
                "🔒 No tienes acceso a este bot.\n"
                "Pide al administrador que agregue tu ID a la lista de usuarios autorizados en Anymotor.",
            )
            return

        if text == "/start":
            _log(f"CMD  [{username}] /start")
            self.send_message(chat_id, (
                "👋 *¡Hola! Soy el agente de Anymotor.*\n\n"
                "Puedo ayudarte a:\n"
                "• 🔍 Buscar autos en Lima, Trujillo o Arequipa\n"
                "• 📋 Ver tu pipeline de deals\n"
                "• 🔗 Analizar un auto (pega la URL de Facebook)\n"
                "• ✏️ Actualizar el estado de un deal\n"
                "• 📊 Ver tu resumen de ganancias\n\n"
                "Escríbeme lo que necesitas en lenguaje normal. ¿Qué buscamos hoy?"
            ))
            return

        if text == "/reset":
            _log(f"CMD  [{username}] /reset")
            self._history.pop(chat_id, None)
            self.send_message(chat_id, "✅ Conversación reiniciada.")
            return

        if text == "/id":
            self.send_message(chat_id, f"Tu Telegram ID es: `{user_id}`")
            return

        self._typing(chat_id)

        # Build / update conversation history
        history = self._history.setdefault(chat_id, [])
        history.append({"role": "user", "content": text})
        if len(history) > 20:
            self._history[chat_id] = history[-20:]

        response = self._run_agent(chat_id, username)
        self._history[chat_id].append({"role": "assistant", "content": response})
        _log(f"RESP [{username}] ← {response[:120].replace(chr(10), ' ')}")
        self.send_message(chat_id, response)

    # ── Agentic loop ──────────────────────────────────────────────────────────

    # Tools whose formatted output is the final answer — no LLM post-processing needed
    _PASSTHROUGH_TOOLS = {"ver_pipeline", "resumen", "buscar_autos", "analizar_url"}

    def _run_agent(self, chat_id: int, username: str = "?") -> str:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self._history[chat_id],
        ]
        # buscar_autos is limited to ONE call per turn (prevents expensive loops).
        # Other tools (e.g. actualizar_estado) may run multiple times (bulk updates).
        single_call_tools = {"buscar_autos", "ver_pipeline", "resumen", "analizar_url"}
        called_once: set[str] = set()

        for iteration in range(8):
            try:
                resp = self.client.chat.completions.create(
                    model=BOT_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.25,
                )
            except Exception as e:
                _log(f"ERR  [{username}] Groq error: {e}")
                return f"⚠️ Error al conectar con la IA: {e}"

            msg_obj = resp.choices[0].message

            if not msg_obj.tool_calls:
                _log(f"LLM  [{username}] respuesta directa (iter {iteration + 1})")
                return msg_obj.content or "No pude generar una respuesta."

            tool_names = [tc.function.name for tc in msg_obj.tool_calls]
            _log(f"LLM  [{username}] llama herramienta(s): {', '.join(tool_names)} (iter {iteration + 1})")

            # Append assistant turn with tool calls
            messages.append({
                "role":       "assistant",
                "content":    msg_obj.content or "",
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg_obj.tool_calls
                ],
            })

            # Execute each tool and append results
            tool_results: dict[str, str] = {}
            for tc in msg_obj.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments) or {}
                except (json.JSONDecodeError, TypeError):
                    args = {}

                if name in single_call_tools and name in called_once:
                    _log(f"SKIP [{username}] {name} ya ejecutado — bloqueado")
                    result = (
                        f"SISTEMA: {name} ya fue ejecutado en este turno. "
                        "NO lo llames de nuevo. Responde al usuario con los resultados anteriores."
                    )
                else:
                    called_once.add(name)
                    _log(f"TOOL [{username}] ejecutando {name}({_fmt_args(args)})")
                    result = self._execute_tool(name, args, chat_id)
                    _log(f"TOOL [{username}] {name} → {result[:80].replace(chr(10), ' ')}")

                tool_results[tc.id] = result
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result,
                })

            # Short-circuit: data-retrieval tools return pre-formatted text — skip LLM re-summarization
            if len(msg_obj.tool_calls) == 1:
                tc0    = msg_obj.tool_calls[0]
                result = tool_results[tc0.id]
                if tc0.function.name in self._PASSTHROUGH_TOOLS and not result.startswith("SISTEMA:"):
                    _log(f"FAST [{username}] respuesta directa de {tc0.function.name}")
                    return result

        _log(f"TIMEOUT [{username}] agotó 8 iteraciones sin respuesta final")
        return "No pude completar la operación en el tiempo límite. Intenta de nuevo."

    # ── Tool dispatcher ───────────────────────────────────────────────────────

    def _execute_tool(self, name: str, args: dict, chat_id: int) -> str:
        if name == "buscar_autos":
            precio_min = int(args.get("precio_min") or 0)
            precio_max = int(args.get("precio_max") or 0)
            modelo     = args.get("modelo", "")
            # If no model specified and no price set, apply default range
            if not modelo and precio_min == 0 and precio_max == 0:
                precio_min, precio_max = 3000, 15000
            sin_filtro = precio_min == 0 and precio_max == 0
            self.send_message(
                chat_id,
                f"🔍 Buscando{' ' + modelo if modelo else ''} en Facebook Marketplace"
                f"{' (sin filtro de precio)' if sin_filtro else ''}... esto tarda 1-2 minutos ⏳",
            )
            return self._tool_buscar_autos(
                ciudad     = args.get("ciudad", "lima"),
                modelo     = modelo,
                precio_min = precio_min,
                precio_max = precio_max,
                cantidad   = min(int(args.get("cantidad") or 3), 5),
            )
        if name == "ver_pipeline":
            return self._tool_ver_pipeline(args.get("estado", "todos"))
        if name == "analizar_url":
            self.send_message(chat_id, "🔎 Analizando el auto... un momento ⏳")
            return self._tool_analizar_url(args.get("url", ""))
        if name == "actualizar_estado":
            return self._tool_actualizar_estado(
                args.get("titulo_parcial", ""),
                args.get("nuevo_estado", ""),
            )
        if name == "resumen":
            return self._tool_resumen()
        return f"Herramienta desconocida: {name}"

    # ── Tool: buscar_autos ────────────────────────────────────────────────────

    def _tool_buscar_autos(
        self,
        ciudad: str = "lima",
        modelo: str = "",
        precio_min: int = 0,
        precio_max: int = 0,
        cantidad: int = 3,
    ) -> str:
        from tools.scraper_tool import FacebookScraper

        async def _run() -> tuple[list[tuple[dict, Any]], int, int]:
            scraper = FacebookScraper(
                city=ciudad, min_price=precio_min, max_price=precio_max, query=modelo
            )
            autos = await scraper.scrape_cars(cantidad)
            orch  = Orchestrator(api_key=self.groq_key)
            aptos: list[tuple[dict, Any]] = []
            rechazados = 0
            for auto in autos:
                if is_seen(auto.get("url", "")):
                    continue
                try:
                    state = await orch.run_acquisition(car_data=auto)
                    mark_seen(auto.get("url", ""), auto.get("title", ""))
                    if state.car_data.get("apto_venta"):
                        aptos.append((auto, state))
                    else:
                        rechazados += 1
                except Exception:
                    rechazados += 1
            return aptos, rechazados, len(autos)

        try:
            aptos, rechazados, total = asyncio.run(_run())
        except Exception as e:
            return f"Error durante la búsqueda: {e}"

        if total == 0:
            return (
                "No se encontraron autos. Facebook puede estar bloqueando el acceso temporalmente. "
                "Intenta en unos minutos o prueba otra ciudad."
            )

        if not aptos:
            return (
                f"Se analizaron {total} auto(s) en {ciudad.title()} pero ninguno es rentable.\n"
                "Prueba con otro modelo o amplía el rango de precio."
            )

        lines = [
            f"✅ *{len(aptos)} oportunidad(es) encontrada(s)* de {total} analizado(s) en {ciudad.title()}:\n"
        ]
        for auto, state in aptos:
            cd  = state.car_data
            pm  = cd.get("precio_mercado") or 0
            pv  = cd.get("precio_venta") or 0
            gan = cd.get("ganancia_est") or 0
            pct = cd.get("margen_pct") or 0
            lines.append(f"🚗 *{auto.get('title', '?')}*")
            lines.append(f"   💵 Publicado: {auto.get('price','?')}  |  Mercado: ${pm:,.0f}")
            lines.append(f"   🎯 Máx. pagar: ${pv:,.0f}  |  💰 Ganancia: ${gan:,.0f} ({pct:.0f}%)")
            if auto.get("url"):
                lines.append(f"   🔗 {auto['url']}")
            if auto.get("whatsapp_number"):
                lines.append(f"   📱 +{auto['whatsapp_number']}")
            lines.append("")
        if rechazados:
            lines.append(f"_({rechazados} auto(s) descartados por no ser rentables)_")
        return "\n".join(lines)

    # ── Tool: ver_pipeline ────────────────────────────────────────────────────

    def _tool_ver_pipeline(self, estado: str = "todos") -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado. Conéctalo en la app web (pestaña Configuración)."

        cars = self.airtable.get_approved_cars(max_records=100)
        if not cars:
            return "📭 No tienes autos guardados aún."

        if estado != "todos":
            cars = [c for c in cars if c.get("Pipeline", "Encontrado") == estado]
            if not cars:
                return f"No tienes autos en estado *{estado}*."

        EMOJIS = {
            "Encontrado": "🔵", "Contactando": "🟡",
            "Negociando": "🟠", "Comprado": "🟣", "Vendido": "🟢",
        }
        groups: dict[str, list] = {}
        for c in cars:
            s = c.get("Pipeline", "Encontrado")
            groups.setdefault(s, []).append(c)

        lines = [f"📋 *Pipeline* ({len(cars)} auto(s)):\n"]
        for stage in ["Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"]:
            grp = groups.get(stage, [])
            if not grp:
                continue
            lines.append(f"{EMOJIS.get(stage, '•')} *{stage}* ({len(grp)})")
            for c in grp:
                title  = str(c.get("Título", "?"))[:50]
                pub    = c.get("Precio Publicado") or 0
                merc   = c.get("Precio Mercado") or 0
                gan_c  = max(merc - pub, 0)
                suffix = f" — +${gan_c:,.0f}" if gan_c else ""
                lines.append(f"  • {title}{suffix}")
            lines.append("")
        return "\n".join(lines)

    # ── Tool: analizar_url ────────────────────────────────────────────────────

    def _tool_analizar_url(self, url: str) -> str:
        if not re.search(r"facebook\.com/marketplace/item/\d+", url):
            return "⚠️ La URL no parece ser un listing válido de Facebook Marketplace."

        from tools.scraper_tool import scrape_item_url

        async def _run():
            car_data = await scrape_item_url(url)
            if not car_data:
                return None
            orch  = Orchestrator(api_key=self.groq_key)
            state = await orch.run_acquisition(car_data=car_data)
            mark_seen(url, car_data.get("title", ""))
            return car_data, state

        try:
            result = asyncio.run(_run())
        except Exception as e:
            return f"Error al analizar el listing: {e}"

        if result is None:
            return "No pude acceder al listing. Puede que Facebook esté bloqueando el acceso."

        car_data, state = result
        cd   = state.car_data
        pm   = cd.get("precio_mercado") or 0
        pv   = cd.get("precio_venta") or 0
        gan  = cd.get("ganancia_est") or 0
        pct  = cd.get("margen_pct") or 0
        apto = bool(cd.get("apto_venta"))

        icon  = "✅" if apto else "❌"
        lines = [
            f"{icon} *{car_data.get('title', '?')}*",
            "",
            f"💵 Publicado: {car_data.get('price','?')}",
            f"📊 Valor mercado: ${pm:,.0f}",
            f"🎯 Máx. a pagar: ${pv:,.0f}",
            f"💰 Ganancia est.: ${gan:,.0f} ({pct:.0f}%)",
            "",
        ]
        red_flags   = cd.get("red_flags", [])
        green_flags = cd.get("green_flags", [])
        if red_flags:
            lines.append("⚠️ *Alertas:*")
            lines.extend(f"  • {f}" for f in red_flags[:4])
            lines.append("")
        if green_flags:
            lines.append("✅ *Puntos a favor:*")
            lines.extend(f"  • {f}" for f in green_flags[:4])
            lines.append("")
        obs = (
            state.inspection_data.get("observaciones")
            or state.inspection_data.get("resultado_inspeccion")
            or ""
        )
        if obs:
            lines.append(f"📋 _{obs[:350]}{'...' if len(obs) > 350 else ''}_")
        if car_data.get("whatsapp_number") and apto:
            lines.append(f"\n📱 WhatsApp vendedor: +{car_data['whatsapp_number']}")
        return "\n".join(lines)

    # ── Tool: actualizar_estado ───────────────────────────────────────────────

    def _tool_actualizar_estado(self, titulo_parcial: str, nuevo_estado: str) -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado."
        if not titulo_parcial:
            return "Necesito el nombre (o parte del nombre) del auto para buscarlo."

        cars = self.airtable.get_approved_cars(max_records=100)
        matches = [
            c for c in cars
            if titulo_parcial.lower() in str(c.get("Título", "")).lower()
        ]

        if not matches:
            return (
                f"No encontré ningún auto que coincida con *{titulo_parcial}*.\n"
                "Verifica el nombre o usa más palabras del título."
            )
        if len(matches) > 1:
            titles = "\n".join(f"• {c.get('Título', '?')}" for c in matches[:5])
            return f"Encontré {len(matches)} coincidencias. Sé más específico:\n{titles}"

        car    = matches[0]
        rec_id = car.get("_id", "")
        result = self.airtable.update_car(rec_id, {"Pipeline": nuevo_estado})
        if result:
            return f"✅ *{car.get('Título','?')}* → *{nuevo_estado}*"
        return "❌ No pude actualizar el registro. Revisa la configuración de Airtable."

    # ── Tool: resumen ─────────────────────────────────────────────────────────

    def _tool_resumen(self) -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado."

        cars = self.airtable.get_approved_cars(max_records=500)
        if not cars:
            return "📭 Aún no tienes datos. Empieza buscando autos desde la app o desde aquí."

        total    = len(cars)
        pipeline: dict[str, int] = {}
        gan_pot  = 0.0
        gan_real = 0.0

        for c in cars:
            stage = c.get("Pipeline", "Encontrado")
            pipeline[stage] = pipeline.get(stage, 0) + 1
            pub      = c.get("Precio Publicado") or 0
            merc     = c.get("Precio Mercado") or 0
            gan_pot  += max(merc - pub, 0)
            gan_real += c.get("Ganancia Real") or 0

        EMOJIS = {
            "Encontrado": "🔵", "Contactando": "🟡",
            "Negociando": "🟠", "Comprado": "🟣", "Vendido": "🟢",
        }
        lines = [f"📊 *Resumen Anymotor* ({total} autos)\n"]
        for stage in ["Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"]:
            count = pipeline.get(stage, 0)
            if count:
                lines.append(f"{EMOJIS.get(stage, '•')} {stage}: {count}")

        lines.append(f"\n💰 Ganancia potencial: *${gan_pot:,.0f}*")
        if gan_real > 0:
            lines.append(f"✅ Ganancia real: *${gan_real:,.0f}*")
            vendidos = pipeline.get("Vendido", 0)
            if vendidos:
                lines.append(f"📈 Promedio por auto vendido: *${gan_real / vendidos:,.0f}*")
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
