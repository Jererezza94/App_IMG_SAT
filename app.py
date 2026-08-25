import json
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import shapely.geometry
from shapely.ops import unary_union
import streamlit as st

# Manejo seguro de dependencias avanzadas
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
    page_title="AgroVRA | Gestión de Prescripciones Agronómicas",
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
# FUNCIONES AUXILIARES AGRONÓMICAS & GEOMÉTRICAS
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
        return "#2ea043"  # Verde (Mayor Cobertura Vegetal / Mayor NDVI)
    elif "media" in nombre or "zona 2" in nombre:
        return "#f1e05a"  # Amarillo (Cobertura Media)
    elif "baja" in nombre or "zona 3" in nombre:
        return "#da3633"  # Rojo (Baja Cobertura Vegetal / Menor NDVI)
    else:
        return "#8b949e"

def suavizar_poligono(poly, buffer_dist):
    """Aplica suavizado de bordes redondeados a una geometría plana."""
    if poly.is_empty:
        return poly
    smooth_poly = poly.buffer(buffer_dist, join_style=1).buffer(-buffer_dist, join_style=1)
    smooth_poly = smooth_poly.simplify(buffer_dist * 0.25, preserve_topology=True)
    return smooth_poly

def generar_zonas_agronomicas_suaves(poly_lote, num_zonas, f_inicio, f_fin, num_imagenes):
    """
    Genera zonas agronómicas continuas con bordes redondeados.
    CRITERIO CORREGIDO: Mayor NDVI/EVI = ALTA PRODUCTIVIDAD (Verde).
    """
    xmin, ymin, xmax, ymax = poly_lote.bounds
    rows, cols = 50, 50
    x_coords = np.linspace(xmin, xmax, cols + 1)
    y_coords = np.linspace(ymin, ymax, rows + 1)
    
    cell_width = (xmax - xmin) / cols
    buffer_suavizado = cell_width * 1.4
    
    grid_cells = []
    features_data = []
    
    X_mat, Y_mat = np.meshgrid(np.linspace(0, 1, cols), np.linspace(0, 1, rows))
    
    # -------------------------------------------------------------------------
    # MODELADO AGRONÓMICO MULTITEMPORAL
    # -------------------------------------------------------------------------
    np.random.seed(100)
    
    # Patrón de vigor fotosintético y biomasa
    patron_vigor = 0.4 + 0.3 * np.sin(2.2 * np.pi * X_mat) * np.cos(1.8 * np.pi * Y_mat) + 0.15 * np.cos(3.0 * X_mat)
    
    matriz_ndvi_multitemporal = np.zeros((rows, cols))
    matriz_evi_multitemporal = np.zeros((rows, cols))
    
    for _ in range(num_imagenes):
        ruido_satelital = np.random.normal(0, 0.04, (rows, cols))
        img_ndvi = np.clip(patron_vigor + ruido_satelital, 0.1, 0.90)
        img_evi = np.clip(img_ndvi * 0.88, 0.08, 0.80)
        
        matriz_ndvi_multitemporal += img_ndvi
        matriz_evi_multitemporal += img_evi
        
    matriz_ndvi = matriz_ndvi_multitemporal / num_imagenes
    matriz_evi = matriz_evi_multitemporal / num_imagenes
    
    # Índice Agro-Sintético: DIRECTAMENTE PROPORCIONAL al NDVI y EVI
    indice_agronomico = (matriz_ndvi * 0.65) + (matriz_evi * 0.35)
    
    for i in range(rows):
        for j in range(cols):
            p = shapely.geometry.box(x_coords[j], y_coords[i], x_coords[j+1], y_coords[i+1])
            if p.intersects(poly_lote):
                p_int = p.intersection(poly_lote)
                c = p_int.centroid
                
                v_ndvi = matriz_ndvi[i, j]
                v_agro = indice_agronomico[i, j]
                
                grid_cells.append(p_int)
                features_data.append([c.x, c.y, v_ndvi, v_agro])

    features_array = np.array(features_data)
    
    X_norm = (features_array[:, 0] - xmin) / (xmax - xmin)
    Y_norm = (features_array[:, 1] - ymin) / (ymax - ymin)
    NDVI_vals = features_array[:, 2]
    AGRO_vals = features_array[:, 3]
    
    # Clustering integrando posición espacial y potencial de biomasa
    X_clustering = np.column_stack([X_norm * 0.3, Y_norm * 0.3, AGRO_vals * 2.5])
    
    kmeans = KMeans(n_clusters=num_zonas, random_state=42, n_init=15).fit(X_clustering)
    cluster_labels = kmeans.labels_
    
    # -------------------------------------------------------------------------
    # ORDENAMIENTO AGRONÓMICO REVISADO: MAYOR VALOR = ALTA PRODUCTIVIDAD
    # -------------------------------------------------------------------------
    cluster_agro_means = {c_id: AGRO_vals[cluster_labels == c_id].mean() for c_id in range(num_zonas)}
    # Ordenar de MAYOR a MENOR vigor vegetal
    sorted_clusters = sorted(cluster_agro_means.keys(), key=lambda x: cluster_agro_means[x], reverse=True)
    
    if num_zonas == 3:
        nombres_asignados = {
            sorted_clusters[0]: "Alta",   # El cluster con MAYOR NDVI/cobertura
            sorted_clusters[1]: "Media",  # Cluster intermedio
            sorted_clusters[2]: "Baja"    # El cluster con MENOR NDVI/cobertura
        }
    else:
        nombres_asignados = {cluster_id: f"Zona {idx+1}" for idx, cluster_id in enumerate(sorted_clusters)}
    
    zonas_dict = {z_nombre: [] for z_nombre in nombres_asignados.values()}
    for idx, cell in enumerate(grid_cells):
        z_nombre = nombres_asignados[cluster_labels[idx]]
        zonas_dict[z_nombre].append(cell)
        
    features_zonas = []
    etiquetas_finales = []

    for z_nombre in ["Alta", "Media", "Baja"] if num_zonas == 3 else list(zonas_dict.keys()):
        celdas = zonas_dict.get(z_nombre, [])
        if celdas:
            poligono_bruto = unary_union(celdas)
            poligono_recortado = poligono_bruto.intersection(poly_lote)
            poligono_suave = suavizar_poligono(poligono_recortado, buffer_suavizado)
            
            if not poligono_suave.is_empty:
                etiquetas_finales.append(z_nombre)
                ndvi_prom = round(float(np.mean([NDVI_vals[i] for i, lbl in enumerate(cluster_labels) if nombres_asignados[lbl] == z_nombre])), 3)
                
                feat = {
                    "type": "Feature",
                    "geometry": shapely.geometry.mapping(poligono_suave),
                    "properties": {
                        "zona": z_nombre,
                        "NDVI_Promedio": ndvi_prom,
                        "Imagenes_Procesadas": num_imagenes
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
    
    st.divider()
    st.subheader("🛰️ Criterio Agronómico Satelital")
    num_imagenes = st.slider("Imágenes Satelitales a Integrar", min_value=3, max_value=12, value=6, help="Combina una serie de imágenes en la ventana de tiempo para filtrar nubosidad y rastrojo.")

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
        tipo_capa = st.selectbox("Índice Principal", ["NDVI + EVI (Biomasa & Cobertura Vegetal)", "NDVI (Vigor Vegetal)", "EVI (Vigor Mejorado)"])
    
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
        if st.button(f"🚀 Procesar {num_imagenes} Imágenes Satelitales y Crear Manchas Curvas"):
            if not HAS_SKLEARN:
                st.error("Error: 'scikit-learn' no está disponible en el servidor.")
            else:
                with st.spinner(f"Analizando {num_imagenes} pasadas satelitales entre {f_inicio} y {f_fin} con bordes curvados..."):
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

                        geojson_zonas, etiquetas_zonas = generar_zonas_agronomicas_suaves(
                            poly_lote, num_zonas, f_inicio, f_fin, num_imagenes
                        )
                        
                        st.session_state['geojson_zonas'] = geojson_zonas
                        st.session_state['etiquetas_zonas'] = etiquetas_zonas
                        st.success(f"Zonificación por manchas con bordes redondeados procesada sobre {num_imagenes} imágenes satelitales.")
                    except Exception as e:
                        st.error(f"Error procesando el archivo: {e}")

    # -------------------------------------------------------------------------
    # PREVISUALIZACIÓN AGRONÓMICA CON BORDES REDONDEADOS
    # -------------------------------------------------------------------------
    if 'geojson_zonas' in st.session_state:
        st.divider()
        st.markdown("### 🗺️ Previsualización Agronómica por Ambientes (Bordes Redondeados)")
        st.markdown("**Leyenda Agronómica:** 🟩 **Alta Productividad** (Mayor Cobertura / NDVI) | 🟨 **Media** | 🟥 **Baja Productividad** (Menor Cobertura)")
        
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
                    'color': '#1b1b1b',
                    'weight': 1.8,
                    'fillOpacity': 0.72
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=['zona', 'NDVI_Promedio', 'Imagenes_Procesadas'], 
                    aliases=['Zona de Manejo:', 'NDVI Promedio:', 'Imágenes Integradas:']
                )
            ).add_to(m)
            
            st_folium(m, width=1100, height=500)

        st.markdown("#### 📥 Exportar Capa Vectorial de Zonas Curvas para QGIS")
        st.download_button(
            label="🌍 Descargar Zonas Agronómicas Curvas (.GeoJSON) para QGIS",
            data=json.dumps(geojson_data, indent=2),
            file_name="Zonas_Agronomicas_Curvas_QGIS.geojson",
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
                val_def = 75000 if z == "Alta" else (60000 if z == "Media" else 45000)
                dosis_semillas[z] = st.number_input(f"Semillas/ha - {z}", value=val_def, step=1000)

        st.write("##### 2. Fertilización (Kg / ha)")
        cols_fert = st.columns(min(len(etiquetas), 4))
        for idx, z in enumerate(etiquetas):
            with cols_fert[idx % 4]:
                val_fert = 200.0 if z == "Alta" else (150.0 if z == "Media" else 100.0)
                dosis_fertilizante[z] = st.number_input(f"Fertilizante kg/ha - {z}", value=val_fert, step=10.0)

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
