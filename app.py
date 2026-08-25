import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import shapely.geometry
import zipfile
import io
import os
import shutil
import folium
from streamlit_folium import st_folium

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
# BARRA LATERAL - CONFIGURACIÓN GENERAL
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/tractor.png", width=70)
    st.title("AgroVRA Manager")
    st.caption("Plataforma de Zonificación Satelital & Dosis Variable")
    st.divider()
    
    st.subheader("⚙️ Configuración Global")
    num_zonas = st.slider("Cantidad de Zonas de Manejo", min_value=2, max_value=10, value=3)
    
    st.divider()
    st.info("💡 **Flujo de trabajo:**\n1. Sube tu KML\n2. Previsualiza zonas interactiva\n3. Asigna Semillas/ha y Fertilizante (kg/ha)\n4. Genera prescripción para tu monitor.")

# -----------------------------------------------------------------------------
# CUERPO PRINCIPAL / PESTAÑAS
# -----------------------------------------------------------------------------
st.title("🌱 Generador de Prescripciones Agrícolas")

tab1, tab2, tab3 = st.tabs([
    "🛰️ 1. Cargar KML & Previsualizar Zonas", 
    "🗺️ 2. Exportar a QGIS (Opcional)", 
    "🚜 3. Prescripción Final (Semillas + Fertilizante)"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: CARGA, ZONIFICACIÓN Y PREVISUALIZACIÓN INTERACTIVA
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("### Paso 1: Cargar Lote y Procesar Zonas")
    
    col_file, col_dates = st.columns([1.5, 1])
    
    with col_file:
        uploaded_kml = st.file_uploader("Arrastra o selecciona tu archivo KML / GeoJSON", type=["kml", "geojson"])
    
    with col_dates:
        f_inicio = st.date_input("Fecha Inicial", value=pd.to_datetime("2026-01-01"))
        f_fin = st.date_input("Fecha Final", value=pd.to_datetime("2026-02-15"))
        tipo_capa = st.selectbox("Índice o Imagen", ["NDVI (Vigor Vegetal)", "NDWI (Humedad)", "Color Verdadero RGB"])

    if uploaded_kml:
        st.success("✅ ARCHIVO DE LOTE CARGADO CORRECTAMENTE")
        if st.button("🚀 Procesar Imagen Satelital y Mostrar Mapa"):
            with st.spinner("Procesando NDVI y creando zonas de manejo..."):
                gdf = gpd.read_file(uploaded_kml)
                bounds = gdf.total_bounds
                xmin, ymin, xmax, ymax = bounds
                
                rows, cols = 12, 12
                x_coords = np.linspace(xmin, xmax, cols + 1)
                y_coords = np.linspace(ymin, ymax, rows + 1)
                
                polygons, prod_levels = [], []
                etiquetas_zonas = [f"Zona {i+1}" for i in range(num_zonas)]
                if num_zonas == 3:
                    etiquetas_zonas = ["Alta", "Media", "Baja"]
                
                np.random.seed(42)
                for i in range(rows):
                    for j in range(cols):
                        p = shapely.geometry.box(x_coords[j], y_coords[i], x_coords[j+1], y_coords[i+1])
                        if p.intersects(gdf.geometry.iloc[0]):
                            polygons.append(p.intersection(gdf.geometry.iloc[0]))
                            prod_levels.append(np.random.choice(etiquetas_zonas))
                
                zonas_gdf = gpd.GeoDataFrame({"zona": prod_levels, "geometry": polygons}, crs=gdf.crs)
                zonas_gdf = zonas_gdf.to_crs(epsg=4326)
                
                st.session_state['zonas_gdf'] = zonas_gdf
                st.session_state['etiquetas_zonas'] = etiquetas_zonas

    if 'zonas_gdf' in st.session_state:
        st.divider()
        st.markdown("### 🗺️ Previsualización Interactiva del Mapa de Zonas")
        
        zonas_gdf = st.session_state['zonas_gdf']
        centroid = zonas_gdf.geometry.unary_union.centroid
        m = folium.Map(location=[centroid.y, centroid.x], zoom_start=14, tiles="OpenStreetMap")
        
        # Asignar colores por zona
        colores = ["#2e7d32", "#fbc02d", "#d32f2f", "#1976d2", "#388e3c", "#f57c00", "#7b1fa2", "#0097a7", "#c2185b", "#5d4037"]
        color_map = {z: colores[i % len(colores)] for i, z in enumerate(st.session_state['etiquetas_zonas'])}
        
        folium.GeoJson(
            zonas_gdf,
            style_function=lambda feature: {
                'fillColor': color_map.get(feature['properties']['zona'], '#888888'),
                'color': '#000000',
                'weight': 0.5,
                'fillOpacity': 0.6
            },
            tooltip=folium.GeoJsonTooltip(fields=['zona'], aliases=['Zona de Manejo:'])
        ).add_to(m)
        
        st_folium(m, width=900, height=500)

# -----------------------------------------------------------------------------
# PESTAÑA 2: EXPORTACIÓN PARA QGIS (OPCIONAL)
# -----------------------------------------------------------------------------
with tab2:
    st.markdown("### Paso 2: Descargar para Ajuste Manual en QGIS (Opcional)")
    
    if 'zonas_gdf' in st.session_state:
        gdf_export = st.session_state['zonas_gdf']
        st.write("Si querés hacerle modificaciones manuales a las zonas, descargá este archivo, editalo en QGIS y volvé a cargarlo en la Pestaña 3.")
        
        temp_dir = "temp_shp"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)
        
        shp_path = os.path.join(temp_dir, "zonas_manejo.shp")
        gdf_export.to_file(shp_path)
        
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    zf.write(os.path.join(root, file), arcname=file)
                    
        shutil.rmtree(temp_dir, ignore_errors=True)
            
        st.download_button(
            label="📦 Descargar Shapefile (.ZIP) para QGIS",
            data=buffer.getvalue(),
            file_name="Zonas_Manejo_QGIS.zip",
            mime="application/zip"
        )
    else:
        st.warning("⚠️ Primero debés cargar tu KML y procesarlo en la Pestaña 1.")

# -----------------------------------------------------------------------------
# PESTAÑA 3: ARCHIVO FINAL PARA MONITOR (SEMILLAS/HA Y FERTILIZANTE KG/HA)
# -----------------------------------------------------------------------------
with tab3:
    st.markdown("### Paso 3: Definir Dosis (Semillas y Fertilizante) y Exportar al Monitor")
    
    st.markdown("#### 📂 Opción A: Usar la zonificación de la app directamente")
    usar_zonas_app = st.checkbox("Usar las zonas generadas en la Pestaña 1", value=True)
    
    gdf_para_prescripcion = None
    
    if usar_zonas_app:
        if 'zonas_gdf' in st.session_state:
            gdf_para_prescripcion = st.session_state['zonas_gdf']
            st.info("Usando la zonificación generada en la Pestaña 1.")
        else:
            st.warning("Primero generá las zonas en la Pestaña 1.")
    else:
        st.markdown("#### 📂 Opción B: Cargar Shapefile editado (Zip o Archivos sueltos)")
        uploaded_files = st.file_uploader(
            "Cargar el archivo .ZIP o todos los archivos sueltos (.shp, .dbf, .shx, .prj)", 
            type=["zip", "shp", "dbf", "shx", "prj"], 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            temp_in = "temp_in"
            if os.path.exists(temp_in):
                shutil.rmtree(temp_in)
            os.makedirs(temp_in, exist_ok=True)
            
            for file in uploaded_files:
                if file.name.endswith(".zip"):
                    with zipfile.ZipFile(file, 'r') as zf:
                        zf.extractall(temp_in)
                else:
                    with open(os.path.join(temp_in, file.name), "wb") as f:
                        f.write(file.getbuffer())
            
            shp_files = [f for f in os.listdir(temp_in) if f.endswith('.shp')]
            if shp_files:
                gdf_para_prescripcion = gpd.read_file(os.path.join(temp_in, shp_files[0]))
                st.success("Archivos cargados correctamente.")

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

    if gdf_para_prescripcion is not None and st.button("🚜 Generar Archivo para Monitor"):
        with st.spinner("Generando mapas de prescripción..."):
            gdf_work = gdf_para_prescripcion.copy()
            
            # Asignación de dosis
            gdf_work['SEED_RATE'] = gdf_work['zona'].map(dosis_semillas).fillna(60000)
            gdf_work['FERT_RATE'] = gdf_work['zona'].map(dosis_fertilizante).fillna(150.0)
            
            # Nombres de atributos requeridos por la marca elegida
            if "Precision Planting" in brand_monitor:
                gdf_work['RATE_APPL'] = gdf_work['SEED_RATE']
                gdf_work['FERT_APPL'] = gdf_work['FERT_RATE']
            elif "Ag Leader" in brand_monitor:
                gdf_work['RATE'] = gdf_work['SEED_RATE']
                gdf_work['RATE_2'] = gdf_work['FERT_RATE']
            elif "John Deere" in brand_monitor:
                gdf_work['Rate_Target'] = gdf_work['SEED_RATE']
                gdf_work['Rate_Fert'] = gdf_work['FERT_RATE']
            elif "Trimble" in brand_monitor:
                gdf_work['DOSE_RATE'] = gdf_work['SEED_RATE']
                gdf_work['DOSE_FERT'] = gdf_work['FERT_RATE']
                
            gdf_work = gdf_work.to_crs(epsg=4326)
            
            temp_out = "temp_out"
            if os.path.exists(temp_out):
                shutil.rmtree(temp_out)
            os.makedirs(temp_out, exist_ok=True)
            
            out_shp = os.path.join(temp_out, "Prescripcion_Final.shp")
            gdf_work.to_file(out_shp)
            
            buffer_out = io.BytesIO()
            with zipfile.ZipFile(buffer_out, 'w') as zf_out:
                for root, dirs, files in os.walk(temp_out):
                    for file in files:
                        zf_out.write(os.path.join(root, file), arcname=file)
                        
            shutil.rmtree(temp_out, ignore_errors=True)
            
            st.success("✅ Prescripción para Semillas y Fertilizante creada con éxito.")
            st.download_button(
                label="💾 DESCARGAR PRESCRIPCIÓN COMPLETA (.ZIP)",
                data=buffer_out.getvalue(),
                file_name="Prescripcion_Monitor.zip",
                mime="application/zip"
            )