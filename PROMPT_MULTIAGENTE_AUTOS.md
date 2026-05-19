# 🚗 Prompt Maestro: Sistema Multiagente — Venta de Autos Usados
> Pega este prompt directamente en tu IDE con IA (Claude Code, Cursor, Copilot, etc.)  
> Ejecuta cada sección **en orden**. No saltes pasos.

---

## CONTEXTO DEL PROYECTO

Estoy construyendo un sistema multiagente para automatizar el proceso de venta de autos usados de un vendedor freelance. El proyecto usa **Python + Antigravity framework + Claude API**.

El proceso tiene 4 flujos principales (basados en un diagrama BPMN TO BE):
1. **Adquisición e Inspección** — identificar autos, inspección física, análisis de precio de mercado automatizado
2. **Preparación y Publicación** — limpieza, fotos, generación de descripción con IA, publicación multicanal vía API
3. **Atención al Cliente / CRM** — chatbot IA que responde preguntas, califica leads, descarta no interesados
4. **Cierre de Venta y Documentación** — negociación, contrato digital, pago, entrega de documentación

La arquitectura es **pipeline multiagente** con un orquestador central y 4 subagentes especializados que se comunican mediante estado compartido y event bus.

---

## PASO 1 — Crear la estructura de carpetas

```
Crea exactamente esta estructura de carpetas en el directorio actual:

used-cars-multiagent/
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── acquisition_agent.py
│   ├── publication_agent.py
│   ├── crm_chatbot_agent.py
│   └── sales_closing_agent.py
├── tools/
│   ├── __init__.py
│   ├── market_price_tool.py
│   ├── image_uploader.py
│   ├── listing_publisher.py
│   └── document_generator.py
├── shared/
│   ├── __init__.py
│   ├── state.py
│   └── event_bus.py
├── data/
│   └── cars_sample.json
├── tests/
│   ├── __init__.py
│   ├── test_acquisition.py
│   ├── test_publication.py
│   ├── test_crm.py
│   ├── test_sales_closing.py
│   └── test_edge_cases.py
├── .env.example
├── requirements.txt
├── main.py
└── README.md
```

No escribas código aún. Solo crea los archivos vacíos y la estructura.

---

## PASO 2 — Instalar dependencias

```
Crea el archivo requirements.txt con exactamente este contenido:

anthropic>=0.25.0
antigravity-ai>=0.3.0
python-dotenv>=1.0.0
httpx>=0.27.0
pydantic>=2.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
rich>=13.0.0
fpdf2>=2.7.0

Luego ejecuta en terminal:
pip install -r requirements.txt
```

---

## PASO 3 — Estado compartido (shared/state.py)

```
Escribe el archivo shared/state.py con una clase CarSaleState usando Pydantic BaseModel.

El estado debe contener estos campos:
- car_id: str (UUID generado automáticamente)
- status: str (valores posibles: "acquired", "published", "negotiating", "sold", "rejected")
- car_data: dict (marca, modelo, año, km, color, precio_mercado, precio_venta, apto_venta: bool)
- inspection_data: dict (resultado_inspeccion, defectos_encontrados: list, score_fisico: int 0-100)
- publication_data: dict (descripcion_generada, urls_publicadas: list, plataformas: list)
- lead_data: dict (nombre_cliente, telefono, email, consultas: list, lead_calificado: bool)
- sale_data: dict (precio_final, forma_pago, contrato_generado: bool, venta_completada: bool)
- events: list[str] (historial de eventos, append-only)
- created_at: datetime
- updated_at: datetime

Agrega un método add_event(event: str) que haga append al historial y actualice updated_at.
Agrega un método to_summary() que retorne un dict con los campos más importantes para mostrar al usuario.

Usa typing apropiado. El estado debe ser completamente serializable a JSON.
```

---

## PASO 4 — Event Bus (shared/event_bus.py)

```
Escribe el archivo shared/event_bus.py con un sistema de eventos simple.

Debe tener:
- Una clase Event con campos: event_type: str, payload: dict, timestamp: datetime, source_agent: str
- Una clase EventBus con:
  - Un diccionario interno de suscriptores (event_type -> lista de callbacks)
  - Método subscribe(event_type: str, callback: callable)
  - Método publish(event: Event) que llama a todos los callbacks suscritos a ese event_type
  - Método get_history() que retorna todos los eventos publicados

Eventos predefinidos como constantes de string:
- CAR_ACQUIRED = "car.acquired"
- INSPECTION_COMPLETED = "inspection.completed"  
- CAR_REJECTED = "car.rejected"
- PUBLICATION_READY = "publication.ready"
- PUBLISHED = "car.published"
- LEAD_RECEIVED = "lead.received"
- LEAD_QUALIFIED = "lead.qualified"
- LEAD_DISCARDED = "lead.discarded"
- NEGOTIATION_STARTED = "negotiation.started"
- SALE_COMPLETED = "sale.completed"
- NEGOTIATION_FAILED = "negotiation.failed"

El event bus debe ser un singleton accesible globalmente.
```

---

## PASO 5 — Agente 1: Adquisición (agents/acquisition_agent.py)

```
Escribe el archivo agents/acquisition_agent.py.

Este agente usa la API de Claude (modelo claude-sonnet-4-20250514) con este system prompt especializado:

SYSTEM PROMPT:
"Eres el Agente de Adquisición de un sistema de venta de autos usados. Tu rol es:
1. Analizar datos de autos candidatos a compra
2. Evaluar si un auto es apto para venta basándote en: año (no mayor a 15 años), km (no más de 200,000), score físico de inspección (mínimo 60/100)
3. Sugerir precio de mercado basado en marca, modelo, año y km usando tu conocimiento actualizado
4. Decidir si se procede con la compra o se rechaza el auto
Responde SIEMPRE en JSON con esta estructura exacta:
{
  'apto_venta': boolean,
  'razon': string,
  'precio_mercado_sugerido': number (en USD),
  'precio_negociacion_recomendado': number (en USD, 15% menos que mercado),
  'observaciones': string
}"

La clase AcquisitionAgent debe tener:
- __init__(self, api_key: str, event_bus: EventBus)
- async analyze_car(self, car_data: dict, inspection_data: dict) -> dict
  - Llama a Claude API con los datos del auto e inspección
  - Parsea la respuesta JSON
  - Actualiza el CarSaleState
  - Publica evento CAR_ACQUIRED o CAR_REJECTED en el event bus
  - Retorna el estado actualizado

Incluye manejo de errores: si Claude no responde JSON válido, reintenta hasta 2 veces.
```

---

## PASO 6 — Agente 2: Publicación (agents/publication_agent.py)

```
Escribe el archivo agents/publication_agent.py.

SYSTEM PROMPT para Claude:
"Eres el Agente de Publicación de un sistema de venta de autos usados. Tu rol es:
1. Generar descripciones atractivas y verídicas para anuncios de autos usados
2. Adaptar el tono según la plataforma: Facebook Marketplace (casual), MercadoLibre (técnico y detallado), Instagram (corto e impactante)
3. Destacar las mejores características del auto sin mentir
4. Incluir siempre: precio, año, km, características principales, estado del auto, forma de contacto
Responde SIEMPRE en JSON con esta estructura:
{
  'descripcion_facebook': string (max 500 chars),
  'descripcion_mercadolibre': string (max 1500 chars, incluye ficha técnica),
  'descripcion_instagram': string (max 200 chars + hashtags),
  'titulo_anuncio': string (max 80 chars),
  'precio_publicar': number,
  'tags_seo': list[string]
}"

La clase PublicationAgent debe tener:
- __init__(self, api_key: str, event_bus: EventBus)
- async generate_listing(self, state: CarSaleState) -> dict
  - Llama a Claude con los datos del auto + resultado de inspección
  - Simula publicación en plataformas (mock: solo loguea las URLs que se generarían)
  - Actualiza publication_data en el estado
  - Publica evento PUBLISHED
  - Retorna URLs simuladas con formato: "https://marketplace.facebook.com/item/{car_id}", etc.

Las URLs son simuladas (mock), no reales. Deja comentarios indicando dónde irían las llamadas reales a APIs externas.
```

---

## PASO 7 — Agente 3: CRM Chatbot (agents/crm_chatbot_agent.py)

```
Escribe el archivo agents/crm_chatbot_agent.py.

SYSTEM PROMPT para Claude:
"Eres el Agente CRM de un sistema de venta de autos usados. Tu rol es:
1. Responder preguntas de clientes potenciales sobre el auto de forma amable y profesional
2. Calificar leads: un lead está calificado si muestra intención real de compra (pregunta por precio final, quiere ver el auto, pregunta por financiamiento o formas de pago)
3. Detectar leads no interesados: solo curiosidad, precios muy bajos irreales, o respuestas evasivas
4. Registrar el motivo de descarte si el lead no califica (para análisis futuro)
Responde SIEMPRE en JSON:
{
  'respuesta_cliente': string (respuesta amable al cliente),
  'lead_calificado': boolean,
  'motivo_descarte': string (solo si lead_calificado es false),
  'siguiente_accion': string ('agendar_cita' | 'seguir_conversacion' | 'descartar'),
  'resumen_intencion': string
}"

La clase CRMChatbotAgent debe tener:
- __init__(self, api_key: str, event_bus: EventBus)
- async handle_message(self, message: str, state: CarSaleState) -> dict
  - Mantiene historial de conversación en state.lead_data['consultas']
  - Llama a Claude con el historial completo + datos del auto como contexto
  - Si lead calificado: publica LEAD_QUALIFIED
  - Si no calificado: publica LEAD_DISCARDED con motivo registrado en CRM
  - Retorna respuesta para mostrar al cliente

El agente DEBE preservar el historial completo de conversación entre llamadas (pasar todas las consultas previas a Claude en cada turno).
```

---

## PASO 8 — Agente 4: Cierre de Venta (agents/sales_closing_agent.py)

```
Escribe el archivo agents/sales_closing_agent.py.

SYSTEM PROMPT para Claude:
"Eres el Agente de Cierre de Venta de un sistema de venta de autos usados. Tu rol es:
1. Gestionar la negociación final del precio
2. Evaluar si una oferta del cliente es aceptable (mínimo: precio_mercado * 0.85)
3. Generar el resumen del contrato de compraventa con todos los datos necesarios
4. Registrar el resultado final: venta completada o negociación fallida
Responde SIEMPRE en JSON:
{
  'oferta_aceptable': boolean,
  'precio_final': number,
  'contraoferta': number (solo si oferta_aceptable es false),
  'resumen_contrato': {
    'vendedor': string,
    'comprador': string,
    'vehiculo': string,
    'precio': number,
    'forma_pago': string,
    'fecha': string,
    'clausulas': list[string]
  },
  'mensaje_cliente': string,
  'venta_completada': boolean
}"

La clase SalesClosingAgent debe tener:
- __init__(self, api_key: str, event_bus: EventBus)
- async negotiate(self, offer: float, state: CarSaleState) -> dict
  - Evalúa si la oferta es aceptable según el precio de mercado
  - Si es aceptable: genera contrato, actualiza estado, publica SALE_COMPLETED
  - Si no es aceptable: genera contraoferta, publica NEGOTIATION_FAILED si ya hubo 3 intentos
  - Retorna resultado

Incluye un contador de intentos de negociación en el estado (máximo 3 antes de cerrar negociación como fallida).
```

---

## PASO 9 — Orquestador (agents/orchestrator.py)

```
Escribe el archivo agents/orchestrator.py.

La clase Orchestrator coordina los 4 agentes en pipeline. Debe:

1. __init__(self, api_key: str):
   - Instanciar el EventBus
   - Instanciar los 4 agentes pasándoles el api_key y el event_bus
   - Suscribir callbacks a los eventos del bus:
     * CAR_ACQUIRED → trigger publication_agent
     * PUBLISHED → loguear con Rich que el auto está publicado
     * LEAD_QUALIFIED → loguear que hay un lead listo para cierre
     * SALE_COMPLETED → generar reporte final

2. async run_acquisition(self, car_data: dict, inspection_data: dict) -> CarSaleState:
   - Crea un CarSaleState nuevo
   - Llama a acquisition_agent.analyze_car()
   - Si apto: llama a publication_agent.generate_listing()
   - Retorna el estado

3. async run_crm(self, message: str, state: CarSaleState) -> dict:
   - Llama a crm_chatbot_agent.handle_message()
   - Retorna respuesta

4. async run_closing(self, offer: float, state: CarSaleState) -> dict:
   - Llama a sales_closing_agent.negotiate()
   - Retorna resultado

5. async run_full_pipeline(self, car_data: dict, inspection_data: dict, client_messages: list[str], final_offer: float) -> dict:
   - Ejecuta el pipeline completo en orden
   - Loguea cada paso con Rich (colores: verde=éxito, rojo=rechazo, amarillo=en proceso)
   - Retorna resumen final del estado

Usa Rich para todos los logs. Usa asyncio para las llamadas async.
```

---

## PASO 10 — Datos de prueba (data/cars_sample.json)

```
Crea el archivo data/cars_sample.json con exactamente 3 autos de ejemplo:

Auto 1 (APTO para venta):
- marca: Toyota, modelo: Corolla, año: 2019, km: 45000, color: Blanco
- precio_dueño: 12000 (USD)
- defectos: ["Rayón leve en puerta trasera izquierda"]
- score_fisico: 82

Auto 2 (RECHAZADO por km excesivo):
- marca: Ford, modelo: F-150, año: 2012, km: 215000, color: Gris
- precio_dueño: 8000 (USD)
- defectos: ["Motor con ruido", "Transmisión desgastada", "Luces delanteras opacas"]
- score_fisico: 38

Auto 3 (CASO BORDE — score físico justo en el límite):
- marca: Honda, modelo: Civic, año: 2017, km: 98000, color: Azul
- precio_dueño: 9500 (USD)
- defectos: ["Parabrisas con grieta pequeña", "AC no enfría bien"]
- score_fisico: 61

Cada auto debe tener también: id (UUID), fecha_inspeccion, inspector_nombre.
```

---

## PASO 11 — Tests (tests/)

```
Crea los siguientes archivos de test usando pytest y pytest-asyncio:

### tests/test_acquisition.py
- test_car_approved: auto Toyota Corolla 2019 45k km → debe retornar apto_venta=True
- test_car_rejected_km: auto con 215k km → debe retornar apto_venta=False
- test_price_suggestion: verificar que precio_mercado_sugerido es un número positivo

### tests/test_publication.py  
- test_description_generated: verificar que genera descripcion_facebook, descripcion_mercadolibre, descripcion_instagram
- test_urls_generated: verificar que publication_data contiene urls_publicadas con 3 URLs

### tests/test_crm.py
- test_qualified_lead: mensaje "¿Cuánto es lo menos que acepta? Quiero ir a verlo mañana" → lead_calificado=True
- test_unqualified_lead: mensaje "¿Puede ser más barato? Solo tengo 3000" → seguir evaluando
- test_conversation_history: verificar que las consultas previas se preservan entre mensajes

### tests/test_edge_cases.py (CASOS ADVERSARIALES — más importantes para la rúbrica)
- test_negotiation_max_attempts: 3 ofertas inaceptables consecutivas → NEGOTIATION_FAILED
- test_car_border_score: auto con score_fisico=60 (límite exacto) → debe ser apto
- test_invalid_car_data: datos de auto incompletos (sin año) → debe lanzar ValueError
- test_empty_client_message: mensaje vacío al CRM → debe responder sin crashear
- test_full_pipeline_rejection: pipeline completo con auto rechazado → estado final = "rejected"

Todos los tests que llamen a la API de Claude deben usar mock (unittest.mock.AsyncMock) para no gastar tokens en tests. Los mocks deben retornar JSONs válidos según el formato de cada agente.
```

---

## PASO 12 — main.py (punto de entrada)

```
Crea el archivo main.py como demo interactivo del sistema completo.

Debe:
1. Cargar API key desde .env (variable ANTHROPIC_API_KEY)
2. Cargar los 3 autos de data/cars_sample.json
3. Mostrar menú con Rich:
   - [1] Ejecutar pipeline completo con Auto 1 (Toyota Corolla — caso exitoso)
   - [2] Ejecutar pipeline completo con Auto 2 (Ford F-150 — caso rechazado)
   - [3] Ejecutar pipeline completo con Auto 3 (Honda Civic — caso borde)
   - [4] Modo interactivo: ingresar datos de auto manualmente
   - [5] Solo probar CRM chatbot (conversación simulada)

Para la opción 1, usar estos datos de cliente simulados:
- Mensajes del cliente: ["¿Está disponible?", "¿Cuál es el precio final?", "Quiero verlo mañana"]
- Oferta final: 11500 USD

Mostrar cada paso del pipeline con timestamps y colores usando Rich.
Al final mostrar un panel resumen con: estado final, precio de venta, tiempo total de ejecución.
```

---

## PASO 13 — .env.example y README

```
Crea el archivo .env.example:

ANTHROPIC_API_KEY=sk-ant-aqui-tu-clave
# Opcional: APIs externas (para publicación real)
FACEBOOK_API_KEY=
MERCADOLIBRE_API_KEY=

---

Crea el archivo README.md con estas secciones exactas:

# Sistema Multiagente — Venta de Autos Usados
## Descripción del proyecto
## Arquitectura (incluir diagrama ASCII del pipeline)
## Tecnologías usadas
## Instalación paso a paso
## Cómo ejecutar
## Cómo ejecutar los tests
## Estructura del proyecto
## Métricas de evaluación
## Autores
```

---

## PASO 14 — Verificación final

```
Cuando hayas terminado todos los pasos anteriores, ejecuta en terminal:

1. python -m pytest tests/ -v --tb=short
2. python main.py

Si hay errores de importación, revisa que todos los __init__.py estén presentes.
Si hay errores de API, verifica que ANTHROPIC_API_KEY esté en el .env.
Reporta: cuántos tests pasaron, cuántos fallaron, y el output de main.py con el Auto 1.
```

---

## CHECKLIST DE LA RÚBRICA (verifica antes de entregar)

| Criterio | Qué verificar |
|---|---|
| ✅ Arquitectura multiagente | ¿Hay 4 agentes con roles únicos + orquestador? |
| ✅ Topología justificada | Pipeline documentado en README con diagrama ASCII |
| ✅ Claude Code tools | ¿Los agentes usan bash, web search (tool use de Claude)? |
| ✅ Prompts especializados | ¿Cada agente tiene su propio system prompt diferente? |
| ✅ Antigravity integrado | ¿Se usa el grafo de agentes y event bus de Antigravity? |
| ✅ MCP / estado compartido | ¿CarSaleState es el estado compartido explícito entre agentes? |
| ✅ Historial preservado | ¿CRM guarda todas las consultas previas en cada turno? |
| ✅ Resolución de conflictos | ¿Negociación tiene máximo de intentos y estado "failed"? |
| ✅ Caso complejo | ¿El pipeline tiene flujos condicionales (apto/no apto, lead/no lead)? |
| ✅ Métricas | ¿main.py muestra tiempo de ejecución y tasa de éxito? |
| ✅ Edge cases | ¿tests/test_edge_cases.py tiene al menos 5 casos adversariales? |
| ✅ README reproducible | ¿Los pasos de instalación y ejecución son claros y completos? |

---

*Proyecto: Automatización Inteligente de Procesos — UPAO 2026-10*  
*Curso: Ingeniería de Sistemas e Inteligencia Artificial — Dr. Luis Vladimir Urrelo Huiman*
