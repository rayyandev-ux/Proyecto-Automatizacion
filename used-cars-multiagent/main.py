from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import FloatPrompt, IntPrompt, Prompt

from agents.orchestrator import Orchestrator


def load_cars() -> list[dict[str, Any]]:
    p = Path(__file__).parent / "data" / "cars_sample.json"
    return json.loads(p.read_text(encoding="utf-8"))


def to_inputs(car: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    car_data = {
        "id": car.get("id"),
        "marca": car.get("marca"),
        "modelo": car.get("modelo"),
        "año": car.get("año"),
        "km": car.get("km"),
        "color": car.get("color"),
        "precio_dueño": car.get("precio_dueño"),
    }

    inspection_data = {
        "resultado_inspeccion": "pendiente",
        "defectos_encontrados": car.get("defectos") or [],
        "score_fisico": car.get("score_fisico"),
        "fecha_inspeccion": car.get("fecha_inspeccion"),
        "inspector_nombre": car.get("inspector_nombre"),
    }

    return car_data, inspection_data


async def run_option(orchestrator: Orchestrator, option: str, console: Console) -> None:
    cars = load_cars()

    if option in {"1", "2", "3"}:
        car = cars[int(option) - 1]
        car_data, inspection_data = to_inputs(car)

        client_messages = ["¿Está disponible?", "¿Cuál es el precio final?", "Quiero verlo mañana"]
        final_offer = 11500.0
        if option == "2":
            client_messages = ["¿Está disponible?", "¿Cuánto cuesta?"]
            final_offer = 3000.0
        if option == "3":
            client_messages = ["¿Está disponible?", "¿Acepta financiamiento?", "Quiero ir a verlo mañana"]
            final_offer = 10500.0

        t0 = time.time()
        summary = await orchestrator.run_full_pipeline(
            car_data=car_data,
            inspection_data=inspection_data,
            client_messages=client_messages,
            final_offer=final_offer,
        )
        total = time.time() - t0
        summary["tiempo_total_s"] = round(total, 2)
        console.print(Panel.fit(json.dumps(summary, ensure_ascii=False, indent=2), title="Resumen"))
        return

    if option == "4":
        marca = Prompt.ask("Marca")
        modelo = Prompt.ask("Modelo")
        anio = IntPrompt.ask("Año")
        km = IntPrompt.ask("KM")
        color = Prompt.ask("Color", default="Sin especificar")
        precio_dueno = FloatPrompt.ask("Precio dueño (USD)")
        score = IntPrompt.ask("Score físico (0-100)", default=70)
        defectos = Prompt.ask("Defectos (separados por coma)", default="").strip()

        car_data = {
            "marca": marca,
            "modelo": modelo,
            "año": anio,
            "km": km,
            "color": color,
            "precio_dueño": precio_dueno,
        }
        inspection_data = {
            "resultado_inspeccion": "manual",
            "defectos_encontrados": [d.strip() for d in defectos.split(",") if d.strip()],
            "score_fisico": score,
        }

        messages = []
        while True:
            msg = Prompt.ask("Mensaje cliente (enter para terminar)", default="").strip()
            if not msg:
                break
            messages.append(msg)

        final_offer = FloatPrompt.ask("Oferta final (USD)", default=float(precio_dueno))
        summary = await orchestrator.run_full_pipeline(
            car_data=car_data,
            inspection_data=inspection_data,
            client_messages=messages,
            final_offer=final_offer,
        )
        console.print(Panel.fit(json.dumps(summary, ensure_ascii=False, indent=2), title="Resumen"))
        return

    if option == "5":
        car = cars[0]
        car_data, inspection_data = to_inputs(car)
        state = await orchestrator.run_acquisition(car_data=car_data, inspection_data=inspection_data)
        console.print(Panel.fit("Modo CRM. Escribe mensajes. Enter para salir.", title="CRM"))
        while True:
            msg = Prompt.ask("Cliente", default="").strip()
            if not msg:
                break
            reply = await orchestrator.run_crm(message=msg, state=state)
            console.print(f"[cyan]Asistente:[/cyan] {reply.get('respuesta_cliente')}")
        return

    console.print("[red]Opción inválida[/red]")


def main() -> None:
    load_dotenv()
    import os

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    console = Console()

    if not api_key:
        console.print(
            Panel.fit(
                "Falta GOOGLE_API_KEY en tu .env. Copia .env.example a .env y configura la clave.",
                title="Configuración requerida",
            )
        )
        return

    orchestrator = Orchestrator(api_key=api_key)

    console.print(
        Panel.fit(
            "\n".join(
                [
                    "[1] Ejecutar pipeline completo con Auto 1 (Toyota Corolla — caso exitoso)",
                    "[2] Ejecutar pipeline completo con Auto 2 (Ford F-150 — caso rechazado)",
                    "[3] Ejecutar pipeline completo con Auto 3 (Honda Civic — caso borde)",
                    "[4] Modo interactivo: ingresar datos de auto manualmente",
                    "[5] Solo probar CRM chatbot (conversación simulada)",
                ]
            ),
            title="Sistema Multiagente — Venta de Autos Usados",
        )
    )

    option = Prompt.ask("Elige una opción", choices=["1", "2", "3", "4", "5"])
    asyncio.run(run_option(orchestrator, option, console))


if __name__ == "__main__":
    main()
