import streamlit as st
import asyncio
import os
from dotenv import load_dotenv

from agents.orchestrator import Orchestrator
from tools.scraper_tool import FacebookScraper
from tools.telegram_tool import TelegramNotifier

load_dotenv()

st.set_page_config(page_title="AutoFlipping MultiAgent", layout="wide")

st.title("🚗 AutoFlipping: Scraper + MultiAgente")

st.sidebar.header("⚙️ Configuración")
google_key = st.sidebar.text_input("Google API Key", value=os.getenv("GOOGLE_API_KEY", ""), type="password")
telegram_token = st.sidebar.text_input("Telegram Bot Token", value=os.getenv("TELEGRAM_BOT_TOKEN", ""), type="password")
telegram_chat = st.sidebar.text_input("Telegram Chat ID", value=os.getenv("TELEGRAM_CHAT_ID", ""))

st.sidebar.header("🔍 Filtros de Búsqueda")
query = st.sidebar.text_input("Buscar (ej. Honda Civic 2010)", value="")
city = st.sidebar.text_input("Ciudad para Scraping", value="lima")
min_price = st.sidebar.number_input("Precio Min", value=3000)
max_price = st.sidebar.number_input("Precio Max", value=25000)
max_items = st.sidebar.slider("Cant. Autos a Scrapear", 1, 10, 3)

if not google_key:
    st.warning("⚠️ Debes configurar la Google API Key para usar los agentes (Gemini).")

if st.sidebar.button("🚀 Iniciar Scraping y Análisis", type="primary"):
    if not google_key:
        st.error("Configura Google API Key primero.")
    else:
        os.environ["GOOGLE_API_KEY"] = google_key
        if telegram_token: os.environ["TELEGRAM_BOT_TOKEN"] = telegram_token
        if telegram_chat: os.environ["TELEGRAM_CHAT_ID"] = telegram_chat
        
        st.info(f"Iniciando scraper en FB Marketplace ({city})...")
        
        scraper = FacebookScraper(city=city, min_price=min_price, max_price=max_price, query=query)
        
        with st.spinner('Scrapeando autos... (esto puede tardar)'):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            autos_scraped = loop.run_until_complete(scraper.scrape_cars(max_items))
            
        if not autos_scraped:
            st.warning("No se encontraron autos o Facebook bloqueó el scraper.")
        else:
            st.success(f"¡Se encontraron {len(autos_scraped)} autos!")
            
            orchestrator = Orchestrator(api_key=google_key)
            telegram = TelegramNotifier()
            
            for auto in autos_scraped:
                st.markdown("---")
                
                col_img, col_info = st.columns([1, 2])
                with col_img:
                    if auto.get("image_url"):
                        st.image(auto.get("image_url"), use_container_width=True)
                    else:
                        st.write("🚗 *(Sin foto)*")
                
                with col_info:
                    safe_title = auto.get('title', 'Sin título').replace('$', r'\$')
                    safe_price = auto.get('price', 'N/A').replace('$', r'\$')
                    st.subheader(f"🚘 {safe_title}")
                    st.write(f"**Precio:** {safe_price}")
                    st.write(f"**URL:** [Ver en Facebook]({auto.get('url', '#')})")
                
                with st.spinner("Analizando oferta con Gemini..."):
                    try:
                        state = loop.run_until_complete(orchestrator.run_acquisition(car_data=auto))
                    except Exception as e:
                        st.error(f"❌ Error al analizar con Gemini: {e}")
                        continue
                    
                if getattr(state, "status", None) in ["acquired", "published"] or state.car_data.get("apto_venta") is True:
                    st.success("✅ **¡BUENA OFERTA DETECTADA!**")
                    observaciones = state.inspection_data.get("observaciones") or state.inspection_data.get("resultado_inspeccion") or ""
                    if observaciones:
                        safe_obs = str(observaciones).replace('$', r'\$')
                        st.info(f"📋 **Análisis:** {safe_obs}")
                    col1, col2 = st.columns(2)
                    with col1:
                        safe_pub_price = auto.get("price", "N/A").replace('$', r'\$')
                        st.metric("💰 Precio publicado", safe_pub_price)
                    with col2:
                        pm = state.car_data.get("precio_mercado")
                        st.metric("📊 Precio mercado (Gemini)", f"\${pm}" if pm else "N/A")
                    if state.car_data.get("precio_venta"):
                        st.metric("🎯 Precio de venta sugerido", f"\${state.car_data.get('precio_venta')}")
                    
                    if telegram_token and telegram_chat:
                        sent = telegram.send_deal_alert(auto, state.car_data)
                        if sent:
                            st.toast("Notificación enviada por Telegram!")
                        else:
                            st.error("Falló envío a Telegram. Revisa el Token/Chat ID.")
                            
                    with st.spinner("Generando publicaciones para revender..."):
                        loop.run_until_complete(orchestrator.publication_agent.generate_listing(state))
                    st.write("**Publicaciones listas:**")
                    st.json(state.publication_data)
                else:
                    st.error("❌ **OFERTA RECHAZADA**")
                    razon = state.car_data.get("error") or state.inspection_data.get("resultado_inspeccion") or state.inspection_data.get("observaciones") or "No cumple con el margen de ganancia o calidad requerida."
                    safe_razon = str(razon).replace('$', r'\$')
                    st.info(f"📋 **Razón:** {safe_razon}")
                    if state.car_data.get("precio_mercado"):
                        st.caption(f"💵 Precio mercado estimado: \${state.car_data.get('precio_mercado')} | Tu límite de precio: \${int(state.car_data.get('precio_mercado', 0) * 0.85)}")

st.markdown("---")
st.markdown("*Sistema Multiagente impulsado por Playwright, Streamlit y Gemini.*")
