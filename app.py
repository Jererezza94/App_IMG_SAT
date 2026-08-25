import streamlit as st
import geopandas as gpd
import json
import ee

st.sidebar.header("🗺️ Selección de Lote")

# Opción para elegir la forma de definir el lote
metodo_lote = st.sidebar.radio(
    "¿Cómo quieres definir el lote?",
    ["Cargar archivo KML / GeoJSON", "Coordenadas manuales"]
)

geometry_ee = None

if metodo_lote == "Cargar archivo KML / GeoJSON":
    uploaded_file = st.sidebar.file_uploader("Sube tu archivo KML o GeoJSON", type=["kml", "geojson", "json"])
    
    if uploaded_file is not None:
        try:
            # Leer el archivo con GeoPandas
            gdf = gpd.read_file(uploaded_file)
            
            # Asegurar proyección WGS84 (EPSG:4326) para Google Earth Engine
            if gdf.crs != "EPSG:4326":
                gdf = gdf.to_crs(epsg=4326)
            
            # Convertir la geometría a GeoJSON y luego a objeto ee.Geometry
            geojson_data = json.loads(gdf.to_json())
            coords = geojson_data['features'][0]['geometry']['coordinates']
            geom_type = geojson_data['features'][0]['geometry']['type']

            if geom_type == "Polygon":
                geometry_ee = ee.Geometry.Polygon(coords)
            elif geom_type == "MultiPolygon":
                geometry_ee = ee.Geometry.MultiPolygon(coords)

            st.sidebar.success("✅ Archivo cargado correctamente")
            
        except Exception as e:
            st.sidebar.error(f"Error al procesar el archivo: {e}")

else:
    # Ingreso por Coordenadas Manuales (Bounding Box)
    st.sidebar.markdown("**Ingresa el recuadro del lote:**")
    min_lon = st.sidebar.number_input("Longitud Mínima (West)", value=-64.50)
    min_lat = st.sidebar.number_input("Latitud Mínima (South)", value=-33.80)
    max_lon = st.sidebar.number_input("Longitud Máxima (East)", value=-64.45)
    max_lat = st.sidebar.number_input("Latitud Máxima (North)", value=-33.75)
    
    geometry_ee = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
