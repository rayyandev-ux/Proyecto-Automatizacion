# Sistema Multiagente — Venta de Autos Usados
## Descripción del proyecto
Sistema multiagente en Python para automatizar la venta de autos usados en un flujo tipo pipeline: adquisición/inspección → publicación → CRM → cierre.

## Arquitectura (incluir diagrama ASCII del pipeline)
```
           +---------------------+
           |     Orchestrator    |
           |  (pipeline + logs)  |
           +----------+----------+
                      |
                      v
   +------------------+------------------+
   | EventBus + CarSaleState compartido  |
   +------------------+------------------+
                      |
                      v
     +----------------+----------------+
     | AcquisitionAgent (LLM Gemini)   |
     +----------------+----------------+
                      |
         apto_venta?  | no
           sí         v
            +---------------------+
            | status = rejected   |
            +---------------------+
                      |
                      v
     +----------------+----------------+
     | PublicationAgent (LLM Gemini)   |
     +----------------+----------------+
                      |
                      v
     +----------------+----------------+
     | CRMChatbotAgent (LLM Gemini)    |
     +----------------+----------------+
                      |
                      v
     +----------------+----------------+
     | SalesClosingAgent (LLM Gemini)  |
     +---------------------------------+
```

## Tecnologías usadas
- Python
- Google Gemini API (HTTP)
- Pydantic
- httpx
- Rich
- pytest + pytest-asyncio
- fpdf2

## Instalación paso a paso
1. Crear entorno virtual (recomendado).
2. Instalar dependencias:
   - `pip install -r requirements.txt`
3. Configurar variables de entorno:
   - Copiar `.env.example` a `.env`
   - Establecer `GOOGLE_API_KEY`

## Cómo ejecutar
- `python main.py`

## Cómo ejecutar los tests
- `python -m pytest tests/ -v --tb=short`

## Estructura del proyecto
- `agents/`: agentes especializados + orquestador
- `shared/`: estado compartido y bus de eventos
- `tools/`: utilidades (mock publicación, generación PDF, etc.)
- `data/`: datos de ejemplo
- `tests/`: suite pytest (con mocks de LLM)

## Métricas de evaluación
- Tasa de éxito del pipeline (aprobación → publicación → lead → venta)
- Tiempo total de ejecución por corrida
- Cobertura de casos adversariales (edge cases)
- Robustez: reintentos ante respuestas no-JSON del LLM

## Autores
- Autor/a: (completar)
