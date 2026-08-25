import streamlit as st
import ee
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.cluster import KMeans

# -----------------------------------------------------------------------------
# 1. INICIALIZACIÓN DE GOOGLE EARTH ENGINE
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Zonificación Agrícola con Sentinel-2 & GEE", layout="wide")

@st.cache_resource
def init_earth_engine(project_id=None):
    """Inicializa la API de Google Earth Engine."""
    try:
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
        return True
    except Exception as e:
        return str(e)

st.title("🌱 Zonificación de Cultivos con Sentinel-2 (Google Earth Engine)")

# Sidebar para credenciales y parámetros de entrada
with st.sidebar:
    st.header("⚙️ Configuración de GEE")
    cloud_project = st.text_input("ID de Proyecto Google Cloud GEE", placeholder="ej: mi-proyecto-gee-123")
    
    ee_status = init_earth_engine(cloud_project if cloud_project else None)
    
    if ee_status is not True:
        st.error(f"Error al conectar con GEE: {ee_status}")
        st.info("Asegúrate de haber ejecutado `earthengine authenticate` en la consola.")
        st.stop()
    else:
        st.success("✅ Conectado exitosamente a Google Earth Engine")

    st.header("📍 Delimitación del Lote (BBOX)")
    col1, col2 = st.columns(2)
    min_lon = col1.number_input("Longitud Mín (West)", value=-64.390, format="%.5f")
    max_lon = col2.number_input("Longitud Máx (East)", value=-64.380, format="%.5f")
    min_lat = col1.number_input("Latitud Mín (South)", value=-33.910, format="%.5f")
    max_lat = col2.number_input("Latitud Máx (North)", value=-33.900, format="%.5f")

    st.header("📅 Rango Temporal")
    fecha_inicio = st.date_input("Fecha Inicio", datetime.now() - timedelta(days=90))
    fecha_fin = st.date_input("Fecha Fin", datetime.now())
    max_clouds = st.slider("Máx. Cobertura de Nubes por escena (%)", 0, 50, 20)

    st.header("📊 Parámetros de Zonificación")
    n_zonas = st.slider("Número de Zonas de Manejo", 2, 5, 3)
    ejecutar = st.button("🚀 Procesar Datos Satelitales")

# -----------------------------------------------------------------------------
# 2. FUNCIONES PARA PROCESAR SENTINEL-2 EN GEE
# -----------------------------------------------------------------------------
def mascara_nubes_sentinel2(image):
    """Aplica la máscara de nubes y cirros basada en la banda QA60 de Sentinel-2."""
    qa = image.select('QA60')
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
    return image.updateMask(mask).divide(10000)

def calcular_ndvi(image):
    """Calcula el índice de vegetación NDVI (B8: Infrarrojo Cercano, B4: Rojo)."""
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    return image.addBands(ndvi)

def obtener_serie_ndvi(geometry, start_date, end_date, cloud_threshold):
    """Consulta la colección de Sentinel-2 L2A y extrae la matriz NDVI."""
    coleccion = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometry)
        .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_threshold))
        .map(mascara_nubes_sentinel2)
        .map(calcular_ndvi)
    )
    
    # Reducimos la colección calculando el percentil 75 o la mediana para eliminar nubes residuales
    ndvi_median = coleccion.select('NDVI').median().clip(geometry)
    ndvi_max = coleccion.select('NDVI').max().clip(geometry)
    
    return ndvi_median, ndvi_max, coleccion.size().getInfo()

# -----------------------------------------------------------------------------
# 3. EJECUCIÓN DEL ANÁLISIS
# -----------------------------------------------------------------------------
if ejecutar:
    with st.spinner("Consultando catálogo de Google Earth Engine..."):
        # Definir área de interés (AOI)
        aoi = ee.Geometry.BBox(min_lon, min_lat, max_lon, max_lat)
        
        # Obtener datos de NDVI
        ndvi_mediana, ndvi_max, total_escenas = obtener_serie_ndvi(aoi, fecha_inicio, fecha_fin, max_clouds)
        
        st.write(f"📷 **Imágenes Sentinel-2 encontradas y procesadas:** {total_escenas}")
        
        if total_escenas == 0:
            st.warning("No se encontraron imágenes sin nubes en el rango seleccionado. Intenta ampliar el rango de fechas o aumentar el % de nubes permitido.")
            st.stop()
        
        # Extraer los datos como matriz NumPy para clustering (resolución a 10m)
        datos_raster = ee.Image.cat([ndvi_mediana.rename('NDVI_Mediana'), ndvi_max.rename('NDVI_Max')])
        
        # Convertir píxeles a array NumPy usando sampleRectangle
        matriz_dict = datos_raster.sampleRectangle(region=aoi, defaultValue=0).getInfo()
        
        arr_mediana = np.array(matriz_dict['properties']['NDVI_Mediana'])
        arr_max = np.array(matriz_dict['properties']['NDVI_Max'])
        
        # Vectorizar los datos ignorando valores nulos
        mask_validos = (~np.isnan(arr_mediana)) & (arr_mediana != 0)
        X = np.column_stack([arr_mediana[mask_validos], arr_max[mask_validos]])

    if len(X) > 0:
        with st.spinner("Generando zonificación de rendimiento mediante K-Means..."):
            # Clustering K-Means sobre la biomasa acumulada y media
            kmeans = KMeans(n_clusters=n_zonas, random_state=42)
            clusters = kmeans.fit_predict(X)
            
            # Reconstruir mapa de zonas
            mapa_zonas = np.zeros_like(arr_mediana)
            mapa_zonas[mask_validos] = clusters + 1  # Zonas numeradas 1, 2, 3...

        # -----------------------------------------------------------------------------
        # 4. RESULTADOS Y VISUALIZACIÓN
        # -----------------------------------------------------------------------------
        st.subheader("📌 Resultados del Análisis Satelital")
        
        tab1, tab2 = st.columns(2)
        
        with tab1:
            st.write("### Mapa de NDVI Promedio (Sentinel-2)")
            st.image(arr_mediana, caption="Vigor Vegetativo (NDVI Mediana)", use_column_width=True, clamp=True)
            
        with tab2:
            st.write("### Mapa de Zonas de Manejo Diferenciado")
            st.image(mapa_zonas / n_zonas, caption=f"Zonificación Agronómica ({n_zonas} niveles)", use_column_width=True, clamp=True)

        # Resumen estadístico por zona
        st.subheader("📈 Resumen por Zona de Manejo")
        df_resumen = pd.DataFrame({
            "NDVI_Mediana": arr_mediana[mask_validos],
            "Zona": clusters + 1
        })
        
        estadisticas = df_resumen.groupby("Zona").agg(
            NDVI_Promedio=("NDVI_Mediana", "mean"),
            NDVI_Minimo=("NDVI_Mediana", "min"),
            NDVI_Maximo=("NDVI_Mediana", "max"),
            Superficie_Relativa=("NDVI_Mediana", lambda x: f"{(len(x) / len(X)) * 100:.1f}%")
        ).reset_index()
        
        st.dataframe(estadisticas, use_container_width=True)
    else:
        st.error("No se pudieron extraer datos válidos para la región seleccionada.")
