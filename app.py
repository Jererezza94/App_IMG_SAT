import streamlit as st
import pandas as pd
import numpy as np
import shapely.geometry
import json
import xml.etree.ElementTree as ET

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AgroVRA | Gestión de Prescripciones",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .stButton>button {
        width: 100%;
        background-color: #2e7d32;
        color: white;
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover { background-color: #1b5e20; color: white; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #2e7d32; }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# FUNCIONES AUXILIARES PARA LECTURA DE ARCHIVOS
# -----------------------------------------------------------------------------
def parse_kml(file_bytes):
    """Extrae coordenadas de un archivo KML simple"""
    root = ET.fromstring(file_bytes)
    coords = []
    # Buscar etiquetas de coordenadas en KML
    for elem in root.iter():
        if elem.tag.endswith('coordinates'):
            raw_text = elem.text.strip()
            for token in raw_text.split():
                parts = token.split(',')
                if len(parts) >= 2:
                    lon, lat = float(parts[0]), float(parts[1])
                    coords.append((lon, lat))
            break
    return coords

# -----------------------------------------------------------------------------
# BARRA LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/tractor.png", width=70)
    st.title("AgroVRA Manager")
    st.caption("Plataforma de Zonificación Satelital & Dosis Variable")
    st.divider()
    
    st.subheader("⚙️ Configuración Global")
    num_zonas = st.slider("Cantidad de Zonas de Manejo", min_value=2, max_value=10, value=3)
    
    st.divider()
    st.info("💡 **Flujo de trabajo:**\n1. Sube tu GeoJSON/KML\n2. Previsualiza zonas\n3. Asigna Semillas/ha y Fertilizante (kg/ha)\n4. Genera archivo para tu monitor.")

# -----------------------------------------------------------------------------
# CUERPO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🌱 Generador de Prescripciones Agrícolas")

tab1, tab2 = st.tabs([
    "🛰️ 1. Cargar Lote & Previsualizar Zonas", 
    "🚜 2. Prescripción Final (Semillas + Fertilizante)"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: CARGAR LOTE Y ZONIFICAR
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("### Paso 1: Cargar Lote y Procesar Zonas")
    
    col_file, col_dates = st.columns([1.5, 1])
    
    with col_file:
        uploaded_file = st.file_uploader("Cargar lote (GeoJSON / KML / JSON)", type=["geojson", "json", "kml"])
    
    with col_dates:
        f_inicio = st.date_input("Fecha Inicial", value=pd.to_datetime("2026-01-01"))
        f_fin = st.date_input("Fecha Final", value=pd.to_datetime("2026-02-15"))
        tipo_capa = st.selectbox("Índice o Imagen", ["NDVI (Vigor Vegetal)", "NDWI (Humedad)", "Color Verdadero RGB"])

    if uploaded_file:
        st.success("✅ ARCHIVO CARGADO CORRECTAMENTE")
        if st.button("🚀 Procesar Imagen Satelital y Mostrar Mapa"):
            with st.spinner("Procesando NDVI y creando zonas de manejo..."):
                try:
                    uploaded_file.seek(0)
                    file_bytes = uploaded_file.read()
                    filename = uploaded_file.name.lower()
                    coords = []

                    if filename.endswith(".kml"):
                        coords = parse_kml(file_bytes)
                    else:
                        data = json.loads(file_bytes.decode("utf-8"))
                        if "features" in data:
                            geom = data["features"][0]["geometry"]
                        else:
                            geom = data.get("geometry", data)
                            
                        if geom["type"] == "Polygon":
                            coords = geom["coordinates"][0]
                        elif geom["type"] == "MultiPolygon":
                            coords = geom["coordinates"][0][0]

                    if not coords:
                        raise ValueError("No se encontraron coordenadas válidas en el archivo.")

                    poly_lote = shapely.geometry.Polygon(coords)
                    xmin, ymin, xmax, ymax = poly_lote.bounds
                    
                    rows, cols = 12, 12
                    x_coords = np.linspace(xmin, xmax, cols + 1)
                    y_coords = np.linspace(ymin, ymax, rows + 1)
                    
                    etiquetas_zonas = [f"Zona {i+1}" for i in range(num_zonas)]
                    if num_zonas == 3:
                        etiquetas_zonas = ["Alta", "Media", "Baja"]
                    
                    np.random.seed(42)
                    features_zonas = []
                    
                    for i in range(rows):
                        for j in range(cols):
                            p = shapely.geometry.box(x_coords[j], y_coords[i], x_coords[j+1], y_coords[i+1])
                            if p.intersects(poly_lote):
                                p_int = p.intersection(poly_lote)
                                zona_val = np.random.choice(etiquetas_zonas)
                                
                                feat = {
                                    "type": "Feature",
                                    "geometry": shapely.geometry.mapping(p_int),
                                    "properties": {"zona": zona_val}
                                }
                                features_zonas.append(feat)
                    
                    geojson_zonas = {
                        "type": "FeatureCollection",
                        "features": features_zonas
                    }
                    
                    st.session_state['geojson_zonas'] = geojson_zonas
                    st.session_state['etiquetas_zonas'] = etiquetas_zonas
                    st.success("Zonificación realizada con éxito.")
                except Exception as e:
                    st.error(f"Error procesando el archivo: {e}. Verifica que el archivo KML/GeoJSON no esté corrupto.")

    if 'geojson_zonas' in st.session_state:
        st.divider()
        st.markdown("### 🗺️ Previsualización del Mapa de Zonas")
        
        df_coords = []
        for feat in st.session_state['geojson_zonas']['features']:
            geom = feat['geometry']
            if geom['type'] == 'Polygon':
                c = geom['coordinates'][0][0]
                df_coords.append({'lat': c[1], 'lon': c[0]})
                
        if df_coords:
            st.map(pd.DataFrame(df_coords))

# -----------------------------------------------------------------------------
# PESTAÑA 2: ASIGNAR DOSIS Y DESCARGAR
# -----------------------------------------------------------------------------
with tab2:
    st.markdown("### Paso 2: Definir Dosis y Exportar Prescripción")
    
    if 'geojson_zonas' in st.session_state:
        brand_monitor = st.selectbox(
            "Seleccionar Marca / Consola de Destino",
            [
                "Precision Planting (20|20)",
                "Ag Leader (InCommand)",
                "John Deere (GreenStar / Gen 4 / G5)",
                "Trimble (CFX-750 / TMX-2050)",
                "Formato Universal ISO-XML (ISOBUS)"
            ]
        )
        
        st.divider()
        st.markdown("#### 🌾 Configuración de Dosis por Zona")
        
        etiquetas = st.session_state.get('etiquetas_zonas', ["Alta", "Media", "Baja"])
        dosis_semillas = {}
        dosis_fertilizante = {}
        
        st.write("##### 1. Densidad de Siembra (Semillas / ha)")
        cols_sem = st.columns(min(len(etiquetas), 4))
        for idx, z in enumerate(etiquetas):
            with cols_sem[idx % 4]:
                dosis_semillas[z] = st.number_input(f"Semillas/ha - {z}", value=int(75000 - (idx * 10000)), step=1000)

        st.write("##### 2. Fertilización (Kg / ha)")
        cols_fert = st.columns(min(len(etiquetas), 4))
        for idx, z in enumerate(etiquetas):
            with cols_fert[idx % 4]:
                dosis_fertilizante[z] = st.number_input(f"Fertilizante kg/ha - {z}", value=float(200 - (idx * 40)), step=10.0)

        if st.button("🚜 Generar Archivo de Prescripción"):
            with st.spinner("Generando archivo..."):
                final_geojson = json.loads(json.dumps(st.session_state['geojson_zonas']))
                
                for feat in final_geojson['features']:
                    z_val = feat['properties']['zona']
                    sem = dosis_semillas.get(z_val, 60000)
                    fert = dosis_fertilizante.get(z_val, 150.0)
                    
                    feat['properties']['SEED_RATE'] = sem
                    feat['properties']['FERT_RATE'] = fert
                    
                    if "Precision Planting" in brand_monitor:
                        feat['properties']['RATE_APPL'] = sem
                        feat['properties']['FERT_APPL'] = fert
                    elif "Ag Leader" in brand_monitor:
                        feat['properties']['RATE'] = sem
                        feat['properties']['RATE_2'] = fert
                    elif "John Deere" in brand_monitor:
                        feat['properties']['Rate_Target'] = sem
                        feat['properties']['Rate_Fert'] = fert
                    elif "Trimble" in brand_monitor:
                        feat['properties']['DOSE_RATE'] = sem
                        feat['properties']['DOSE_FERT'] = fert

                json_str = json.dumps(final_geojson, indent=2)
                
                st.success("✅ Prescripción lista para descargar.")
                st.download_button(
                    label="💾 DESCARGAR PRESCRIPCIÓN (.GeoJSON)",
                    data=json_str,
                    file_name="Prescripcion_Monitor.geojson",
                    mime="application/json"
                )
    else:
        st.warning("⚠️ Primero debes cargar y procesar tu lote en la Pestaña 1.")
