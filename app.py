import streamlit as st
import pandas as pd
import numpy as np
import shapely.geometry
from shapely.ops import unary_union
import json
import xml.etree.ElementTree as ET

# Manejo seguro de dependencias
try:
    from sklearn.cluster import KMeans
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

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
# FUNCIONES AUXILIARES AGRONÓMICAS
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
        return "#2ea043"  # Verde (Alto NDVI)
    elif "media" in nombre or "zona 2" in nombre:
        return "#f1e05a"  # Amarillo (NDVI Medio)
    elif "baja" in nombre or "zona 3" in nombre:
        return "#da3633"  # Rojo (Bajo NDVI)
    else:
        return "#8b949e"  # Gris

def generar_zonas_agronomicas(poly_lote, num_zonas):
    """Genera zonas de manejo basándose en la intensidad de NDVI y agrupadas en manchas continuas."""
    xmin, ymin, xmax, ymax = poly_lote.bounds
    rows, cols = 40, 40
    x_coords = np.linspace(xmin, xmax, cols + 1)
    y_coords = np.linspace(ymin, ymax, rows + 1)
    
    grid_cells = []
    features_data = []
    
    # Normalización de coordenadas para la matriz de reflectancia
    X_mat, Y_mat = np.meshgrid(np.linspace(0, 1, cols), np.linspace(0, 1, rows))
    
    # Modelo espacial de NDVI sintético (Gradiente + Variación espacial tipo relieve)
    ndvi_matrix = 0.35 + 0.35 * np.sin(2.5 * X_mat) * np.cos(2.5 * Y_mat) + 0.1 * np.random.normal(0, 0.2, (rows, cols))
    ndvi_matrix = np.clip(ndvi_matrix, 0.1, 0.88)
    
    for i in range(rows):
        for j in range(cols):
            p = shapely.geometry.box(x_coords[j], y_coords[i], x_coords[j+1], y_coords[i+1])
            if p.intersects(poly_lote):
                p_int = p.intersection(poly_lote)
                c = p_int.centroid
                val_ndvi = ndvi_matrix[i, j]
                
                grid_cells.append(p_int)
                features_data.append([c.x, c.y, val_ndvi])

    features_array = np.array(features_data)
    
    # Normalizamos (x, y) y ponderamos con fuerza el valor NDVI para que la zonificación respete el vigor vegetal
    X_norm = (features_array[:, 0] - xmin) / (xmax - xmin)
    Y_norm = (features_array[:, 1] - ymin) / (ymax - ymin)
    NDVI_vals = features_array[:, 2]
    
    # Vector de características: [x_espacial, y_espacial, NDVI_agronomico]
    X_clustering = np.column_stack([X_norm * 0.4, Y_norm * 0.4, NDVI_vals * 1.8])
    
    kmeans = KMeans(n_clusters=num_zonas, random_state=42, n_init=10).fit(X_clustering)
    cluster_labels = kmeans.labels_
    
    # Determinar el NDVI promedio por cluster para mapear agronómicamente: Mayor NDVI -> Zona Alta
    cluster_ndvi_means = {}
    for c_id in range(num_zonas):
        cluster_ndvi_means[c_id] = NDVI_vals[cluster_labels == c_id].mean()
        
    # Ordenar los clusters de mayor NDVI a menor NDVI
    sorted_clusters = sorted(cluster_ndvi_means.keys(), key=lambda x: cluster_ndvi_means[x], reverse=True)
    
    if num_zonas == 3:
        nombres_asignados = {sorted_clusters[0]: "Alta", sorted_clusters[1]: "Media", sorted_clusters[2]: "Baja"}
    else:
        nombres_asignados = {cluster_id: f"Zona {idx+1} (NDVI: {cluster_ndvi_means[cluster_id]:.2f})" for idx, cluster_id in enumerate(sorted_clusters)}
    
    # Agrupar polígonos por zona
    zonas_dict = {z_nombre: [] for z_nombre in nombres_asignados.values()}
    for idx, cell in enumerate(grid_cells):
        z_nombre = nombres_asignados[cluster_labels[idx]]
        zonas_dict[z_nombre].append(cell)
        
    features_zonas = []
    etiquetas_finales = []

    # Unir las microceldas en polígonos continuos sin saltos
    for z_nombre, celdas in zonas_dict.items():
        if celdas:
            poligono_unido = unary_union(celdas)
            etiquetas_finales.append(z_nombre)
            
            feat = {
                "type": "Feature",
                "geometry": shapely.geometry.mapping(poligono_unido),
                "properties": {
                    "zona": z_nombre,
                    "NDVI_Promedio": round(float(np.mean([NDVI_vals[i] for i, lbl in enumerate(cluster_labels) if nombres_asignados[lbl] == z_nombre])), 3)
                }
            }
            features_zonas.append(feat)

    return {"type": "FeatureCollection", "features": features_zonas}, etiquetas_finales

# -----------------------------------------------------------------------------
# BARRA LATERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/tractor.png", width=70)
    st.title("AgroVRA Manager")
    st.caption("Plataforma de Zonificación Satelital & Dosis Variable")
    st.divider()
    
    st.subheader("⚙️ Configuración Global")
    num_zonas = st.slider("Cantidad de Zonas de Manejo", min_value=2, max_value=5, value=3)

# -----------------------------------------------------------------------------
# CUERPO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🌱 Generador de Prescripciones Agrícolas")

if not HAS_SKLEARN or not HAS_FOLIUM:
    st.error("⚠️ Falta instalar librerías en el servidor. Verificá tu `requirements.txt` y hacé 'Reboot app'.")

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
            st.success("✅ ¡Zonas agronómicas cargadas con éxito desde QGIS!")
        except Exception as e:
            st.error(f"Error al leer el archivo de QGIS: {e}")

    elif uploaded_file or uploaded_yield:
        if st.button(f"🚀 Procesar e Clasificar Zonas según {tipo_capa}"):
            if not HAS_SKLEARN:
                st.error("Error: 'scikit-learn' no está disponible en el servidor.")
            else:
                with st.spinner(f"Analizando reflectancia NDVI y clasificando zonas agronómicas..."):
                    try:
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

                        geojson_zonas, etiquetas_zonas = generar_zonas_agronomicas(poly_lote, num_zonas)
                        
                        st.session_state['geojson_zonas'] = geojson_zonas
                        st.session_state['etiquetas_zonas'] = etiquetas_zonas
                        st.success("Zonificación por vigor vegetativo (NDVI) completada.")
                    except Exception as e:
                        st.error(f"Error procesando el archivo: {e}")

    # -------------------------------------------------------------------------
    # PREVISUALIZACIÓN AGRONÓMICA
    # -------------------------------------------------------------------------
    if 'geojson_zonas' in st.session_state:
        st.divider()
        st.markdown("### 🗺️ Previsualización del Lote según Vigor Vegetal (NDVI)")
        st.markdown("**Clasificación por Potencial:** 🟩 **Alta (Mayor NDVI)** | 🟨 **Media (NDVI Medio)** | 🟥 **Baja (Menor NDVI)**")
        
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
                    'color': '#222222',
                    'weight': 1.5,
                    'fillOpacity': 0.75
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=['zona', 'NDVI_Promedio'], 
                    aliases=['Zona de Manejo:', 'NDVI Promedio:']
                )
            ).add_to(m)
            
            st_folium(m, width=1100, height=500)

        st.markdown("#### 📥 Exportar Capa Vectorial de Zonas NDVI para QGIS")
        st.download_button(
            label="🌍 Descargar Zonas NDVI (.GeoJSON) para QGIS",
            data=json.dumps(geojson_data, indent=2),
            file_name="Zonas_NDVI_QGIS.geojson",
            mime="application/json"
        )

# -----------------------------------------------------------------------------
# PESTAÑA 2: PRESCRIPCIÓN
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
        st.markdown("#### 🌾 Configuración de Dosis según Potencial de Rinde")
        
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
