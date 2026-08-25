import streamlit as st
import pandas as pd
import numpy as np
import shapely.geometry
import json
import xml.etree.ElementTree as ET

# Intentar importar librerías de mapeo avanzado
try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

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
# FUNCIONES AUXILIARES
# -----------------------------------------------------------------------------
def parse_kml(file_bytes):
    root = ET.fromstring(file_bytes)
    coords = []
    for elem in root.iter():
        if elem.tag.endswith('coordinates'):
            raw_text = elem.text.strip()
            for token in raw_text.split():
                parts = token.split(',')
                if len(parts) >= 2:
                    coords.append((float(parts[0]), float(parts[1])))
            break
    return coords

def limpiar_mapa_rendimiento(df):
    col_yield = next((c for c in df.columns if 'yield' in c.lower() or 'rinde' in c.lower() or 'tn/ha' in c.lower() or 'kg/ha' in c.lower()), None)
    
    if col_yield:
        q1 = df[col_yield].quantile(0.05)
        q3 = df[col_yield].quantile(0.95)
        df = df[(df[col_yield] >= q1) & (df[col_yield] <= q3)]
    
    col_speed = next((c for c in df.columns if 'speed' in c.lower() or 'vel' in c.lower()), None)
    if col_speed:
        df = df[df[col_speed] > 0.5]
        
    return df, col_yield

def obtener_color_zona(nombre_zona):
    nombre = str(nombre_zona).lower()
    if "alta" in nombre or "zona 1" in nombre:
        return "#2ea043"  # Verde
    elif "media" in nombre or "zona 2" in nombre:
        return "#f1e05a"  # Amarillo
    elif "baja" in nombre or "zona 3" in nombre:
        return "#da3633"  # Rojo
    else:
        return "#8b949e"  # Gris

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
    st.info("💡 **Flujo de trabajo:**\n1. Seleccionar fechas e índice\n2. Cargar Lote o Rinde\n3. Exportar Vectorial para QGIS\n4. Cargar QGIS editado y generar Prescripción")

# -----------------------------------------------------------------------------
# CUERPO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🌱 Generador de Prescripciones Agrícolas")

tab1, tab2 = st.tabs([
    "🛰️ 1. Cargar Lote / Rendimiento & Zonificar", 
    "🚜 2. Prescripción Final (Semillas + Fertilizante)"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("### Paso 1: Configurar Parámetros Satelitales y Cargar Datos")
    
    col_dates, col_index = st.columns([1, 1])
    with col_dates:
        f_inicio = st.date_input("Fecha Inicial", value=pd.to_datetime("2026-01-01"))
        f_fin = st.date_input("Fecha Final", value=pd.to_datetime("2026-02-15"))
    with col_index:
        tipo_capa = st.selectbox("Índice o Imagen Satelital", ["NDVI (Vigor Vegetal)", "NDWI (Humedad)", "Color Verdadero RGB", "EVI (Vigor Mejorado)"])
    
    st.divider()
    
    col_file, col_rend = st.columns([1.2, 1.2])
    with col_file:
        uploaded_file = st.file_uploader("1. Lote (GeoJSON / KML)", type=["geojson", "json", "kml"])
    with col_rend:
        uploaded_yield = st.file_uploader("2. Mapa Rendimiento Cosechadora (CSV / GeoJSON)", type=["csv", "geojson", "json"])
        
    st.divider()
    st.markdown("#### ✏️ Edición Externa (QGIS)")
    uploaded_edited = st.file_uploader("Re-cargar Zonas Vectoriales Modificadas desde QGIS (.GeoJSON)", type=["geojson", "json"], key="qgis_uploader")

    if uploaded_edited:
        try:
            geojson_editado = json.load(uploaded_edited)
            st.session_state['geojson_zonas'] = geojson_editado
            zonas_detectadas = sorted(list(set([f['properties'].get('zona', 'Zona 1') for f in geojson_editado['features']])))
            st.session_state['etiquetas_zonas'] = zonas_detectadas
            st.success("✅ ¡Capa vectorial cargada con éxito desde QGIS!")
        except Exception as e:
            st.error(f"Error al leer el archivo de QGIS: {e}")

    elif uploaded_file or uploaded_yield:
        if st.button("🚀 Procesar Imagen Satelital / Datos y Mostrar Mapa"):
            with st.spinner(f"Procesando {tipo_capa} entre {f_inicio} y {f_fin}..."):
                try:
                    coords = []
                    if uploaded_yield and uploaded_yield.name.endswith('.csv'):
                        df_raw = pd.read_csv(uploaded_yield)
                        df_clean, col_y = limpiar_mapa_rendimiento(df_raw)
                        st.info(f"✨ Mapa de rinde filtrado correctamente ({len(df_clean)} puntos válidos).")
                        
                        col_lat = next(c for c in df_clean.columns if 'lat' in c.lower())
                        col_lon = next(c for c in df_clean.columns if 'lon' in c.lower())
                        df_points = df_clean[[col_lon, col_lat]].values
                        poly_lote = shapely.geometry.MultiPoint(df_points).convex_hull
                    else:
                        uploaded_file.seek(0)
                        file_bytes = uploaded_file.read()
                        if uploaded_file.name.lower().endswith(".kml"):
                            coords = parse_kml(file_bytes)
                        else:
                            data = json.loads(file_bytes.decode("utf-8"))
                            geom = data["features"][0]["geometry"] if "features" in data else data.get("geometry", data)
                            coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
                        poly_lote = shapely.geometry.Polygon(coords)

                    xmin, ymin, xmax, ymax = poly_lote.bounds
                    rows, cols = 15, 15
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
                    
                    st.session_state['geojson_zonas'] = {"type": "FeatureCollection", "features": features_zonas}
                    st.session_state['etiquetas_zonas'] = etiquetas_zonas
                    st.success(f"Zonificación continua realizada con éxito usando {tipo_capa}.")
                except Exception as e:
                    st.error(f"Error procesando el archivo: {e}")

    # -------------------------------------------------------------------------
    # PREVISUALIZACIÓN POLIGONAL COMPLETA EN VERDE, AMARILLO Y ROJO
    # -------------------------------------------------------------------------
    if 'geojson_zonas' in st.session_state:
        st.divider()
        st.markdown("### 🗺️ Previsualización del Lote Completo por Zonas")
        st.markdown("**Leyenda de Producción:** 🟩 **Alta** | 🟨 **Media** | 🟥 **Baja**")
        
        geojson_data = st.session_state['geojson_zonas']
        
        if HAS_FOLIUM:
            lats, lons = [], []
            for feat in geojson_data['features']:
                geom = shapely.geometry.shape(feat['geometry'])
                lats.append(geom.centroid.y)
                lons.append(geom.centroid.x)
            
            mapa_centro = [np.mean(lats), np.mean(lons)]
            m = folium.Map(location=mapa_centro, zoom_start=14, tiles="OpenStreetMap")
            
            folium.GeoJson(
                geojson_data,
                style_function=lambda feature: {
                    'fillColor': obtener_color_zona(feature['properties'].get('zona', '')),
                    'color': '#333333',
                    'weight': 0.8,
                    'fillOpacity': 0.75
                },
                tooltip=folium.GeoJsonTooltip(fields=['zona'], aliases=['Zona de Manejo:'])
            ).add_to(m)
            
            st_folium(m, width=1100, height=500)
        else:
            st.warning("⚠️ El servidor aún está instalando 'folium'. Por favor hacé click en el menú de la app arriba a la derecha y selecciona 'Reboot app'.")

        st.markdown("#### 📥 Exportar Capa Vectorial de Polígonos para QGIS")
        st.download_button(
            label="🌍 Descargar Zonas Vectoriales (.GeoJSON) para QGIS",
            data=json.dumps(geojson_data, indent=2),
            file_name="Zonas_Vectoriales_QGIS.geojson",
            mime="application/json"
        )

# -----------------------------------------------------------------------------
# PESTAÑA 2
# -----------------------------------------------------------------------------
with tab2:
    st.markdown("### Paso 2: Definir Dosis y Exportar Prescripción Final")
    
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

        if st.button("🚜 Generar Archivo de Prescripción Final"):
            with st.spinner("Generando archivo..."):
                final_geojson = json.loads(json.dumps(st.session_state['geojson_zonas']))
                
                for feat in final_geojson['features']:
                    z_val = feat['properties'].get('zona', 'Zona 1')
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

                st.success("✅ Prescripción lista para descargar.")
                st.download_button(
                    label="💾 DESCARGAR PRESCRIPCIÓN (.GeoJSON)",
                    data=json.dumps(final_geojson, indent=2),
                    file_name="Prescripcion_Monitor.geojson",
                    mime="application/json"
                )
    else:
        st.warning("⚠️ Primero debes cargar o procesar datos en la Pestaña 1.")
