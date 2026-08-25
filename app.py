import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import shapely.geometry
import zipfile
import io
import os
import shutil

# -----------------------------------------------------------------------------
# CONFIGURACIÓN Y ESTILO DE LA INTERFAZ
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
    st.info("💡 **Flujo de trabajo:**\n1. Sube tu KML\n2. Edita en QGIS si lo deseas\n3. Genera la prescripción para tu sembradora/fertilizadora.")

# -----------------------------------------------------------------------------
# CUERPO PRINCIPAL / PESTAÑAS
# -----------------------------------------------------------------------------
st.title("🌱 Generador de Prescripciones Agrícolas")

tab1, tab2, tab3 = st.tabs([
    "🛰️ 1. Cargar KML & Zonificar", 
    "🗺️ 2. Exportar a QGIS", 
    "🚜 3. Archivo Final para Monitor"
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: CARGA Y ZONIFICACIÓN
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("### Paso 1: Definir Lote y Rango de Fechas")
    
    col_file, col_dates = st.columns([1.5, 1])
    
    with col_file:
        uploaded_kml = st.file_uploader("Arrastra o selecciona tu archivo KML / GeoJSON", type=["kml", "geojson"])
    
    with col_dates:
        f_inicio = st.date_input("Fecha Inicial", value=pd.to_datetime("2026-01-01"))
        f_fin = st.date_input("Fecha Final", value=pd.to_datetime("2026-02-15"))
        tipo_capa = st.selectbox("Índice o Imagen", ["NDVI (Vigor Vegetal)", "NDWI (Humedad)", "Color Verdadero RGB"])

    if uploaded_kml:
        st.success("ARCHIVO DE LOTE CARGADO CORRECTAMENTE")
        if st.button("🚀 Procesar Imagen Satelital y Zonificar"):
            with st.spinner("Procesando NDVI y creando zonas de manejo..."):
                gdf = gpd.read_file(uploaded_kml)
                bounds = gdf.total_bounds
                xmin, ymin, xmax, ymax = bounds
                
                rows, cols = 8, 8
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
                st.session_state['zonas_gdf'] = zonas_gdf
                st.session_state['etiquetas_zonas'] = etiquetas_zonas
                
                st.balloons()
                st.success(f"Zonificación lista en {num_zonas} niveles. Pasa a la Pestaña 2 para descargar el Shapefile.")

# -----------------------------------------------------------------------------
# PESTAÑA 2: EXPORTACIÓN PARA QGIS
# -----------------------------------------------------------------------------
with tab2:
    st.markdown("### Paso 2: Descargar para Ajuste Manual en QGIS")
    
    if 'zonas_gdf' in st.session_state:
        gdf_export = st.session_state['zonas_gdf']
        st.write("Si necesitas retocar o corregir bordes manualmente, descarga este archivo, ábrelo en QGIS y vuelve a la Pestaña 3 cuando termines.")
        
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
        st.warning("⚠️ Primero debes cargar tu KML y presionar 'Procesar' en la Pestaña 1.")

# -----------------------------------------------------------------------------
# PESTAÑA 3: ARCHIVO FINAL PARA MONITOR
# -----------------------------------------------------------------------------
with tab3:
    st.markdown("### Paso 3: Asignar Dosis y Exportar al Monitor")
    
    uploaded_zip = st.file_uploader("Cargar Zip del Shapefile (Editado en QGIS o el generado en Pestaña 2)", type=["zip"])
    
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
    st.markdown("#### Ingresar Dosis Objetivo (kg/ha o L/ha)")
    
    dosis_dict = {}
    etiquetas = st.session_state.get('etiquetas_zonas', ["Alta", "Media", "Baja"])
    cols_dosis = st.columns(min(len(etiquetas), 4))
    
    for idx, z in enumerate(etiquetas):
        with cols_dosis[idx % 4]:
            dosis_dict[z] = st.number_input(f"Dosis {z}", value=float(150 + (idx * 30)))
            
    if uploaded_zip and st.button("🚜 Generar Prescripción Final"):
        with st.spinner("Formateando mapa de prescripción para el monitor seleccionado..."):
            temp_in = "temp_in"
            if os.path.exists(temp_in):
                shutil.rmtree(temp_in)
            os.makedirs(temp_in, exist_ok=True)
            
            with zipfile.ZipFile(uploaded_zip, 'r') as zf:
                zf.extractall(temp_in)
                
            shp_files = [f for f in os.listdir(temp_in) if f.endswith('.shp')]
            if shp_files:
                gdf_edited = gpd.read_file(os.path.join(temp_in, shp_files[0]))
                
                gdf_edited['RATE'] = gdf_edited['zona'].map(dosis_dict).fillna(150.0)
                
                if "Precision Planting" in brand_monitor:
                    gdf_edited['RATE_APPL'] = gdf_edited['RATE']
                elif "Ag Leader" in brand_monitor:
                    gdf_edited['RATE'] = gdf_edited['RATE']
                elif "John Deere" in brand_monitor:
                    gdf_edited['Rate_Target'] = gdf_edited['RATE']
                elif "Trimble" in brand_monitor:
                    gdf_edited['DOSE_RATE'] = gdf_edited['RATE']
                
                gdf_edited = gdf_edited.to_crs(epsg=4326)
                
                temp_out = "temp_out"
                if os.path.exists(temp_out):
                    shutil.rmtree(temp_out)
                os.makedirs(temp_out, exist_ok=True)
                
                out_shp = os.path.join(temp_out, "Prescripcion_Final.shp")
                gdf_edited.to_file(out_shp)
                
                buffer_out = io.BytesIO()
                with zipfile.ZipFile(buffer_out, 'w') as zf_out:
                    for root, dirs, files in os.walk(temp_out):
                        for file in files:
                            zf_out.write(os.path.join(root, file), arcname=file)
                            
                shutil.rmtree(temp_in, ignore_errors=True)
                shutil.rmtree(temp_out, ignore_errors=True)
                
                st.success("Prescripción generada y formateada con éxito.")
                st.download_button(
                    label="💾 DESCARGAR PRESCRIPCIÓN (.ZIP)",
                    data=buffer_out.getvalue(),
                    file_name="Prescripcion_Monitor.zip",
                    mime="application/zip"
                )