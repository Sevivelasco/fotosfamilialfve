import streamlit as st
import pandas as pd
import gcsfs
import io
from PIL import Image
import os
import time

# --- 1. CONFIGURACIÓN DE NUBE (GCS) ---
# ¡NOMBRE DE BUCKET CORREGIDO!
BUCKET_NAME = "fotosfamilialfve" 
# La ruta base de las fotos en tu Bucket (asumimos que FOTOSCO, FOTOSVE, hijos están en la raíz del Bucket)
GCS_BASE_PATH = f"gs://{BUCKET_NAME}/" 

# Inicialización del FileSystem de GCS
@st.cache_resource
def init_gcs_fs():
    try:
        # Intenta inicializar GCS FileSystem.
        fs = gcsfs.GCSFileSystem()
        st.success("Conexión a Google Cloud Storage lista.")
        return fs
    except Exception as e:
        st.error(f"Error al inicializar GCS FileSystem. Verifique la configuración de su llave JSON o permisos. Error: {e}")
        return None

fs = init_gcs_fs()
if not fs:
    st.stop() # Detiene la aplicación si la conexión falla.

# Definición de las consultas (Mapeo de rutas de Excel a carpetas de GCS)
consultas_individuales = {
    "1": {
        "nombre": "FAMILIA CONER",
        "ruta_excel": "t_fotos coner.xlsx", 
        "carpeta_fotos": "FOTOSCO" 
    },
    "2": {
        "nombre": "FAMILIA VELASCO ESPINOSA",
        "ruta_excel": "fotos.xlsx",
        "carpeta_fotos": "FOTOSVE"
    },
    "3": {
        "nombre": "FAMILIA VELASCO ENDARA",
        "ruta_excel": "hijos.xlsx",
        "carpeta_fotos": "HIJOS"
    }
}

consultas_globales = {
    "41": {"nombre": "CONSULTA GLOBAL (Orden 1, 2, 3)", "orden_carga": ["1", "2", "3"]},
    "42": {"nombre": "CONSULTA GLOBAL (Orden 2, 1, 3)", "orden_carga": ["2", "1", "3"]},
    "43": {"nombre": "CONSULTA GLOBAL (Orden 3, 1, 2)", "orden_carga": ["3", "1", "2"]}
}
consultas = {**consultas_individuales, **consultas_globales}


# --- 2. GESTIÓN DEL ESTADO Y DATOS ---

# Usamos st.session_state para almacenar variables (como las globales de Tkinter)
if 'menu_state' not in st.session_state:
    st.session_state.menu_state = 'INICIO'
if 'df_cache' not in st.session_state:
    st.session_state.df_cache = {} # Caché para los DataFrames individuales
if 'filtered_results' not in st.session_state:
    st.session_state.filtered_results = pd.DataFrame()
if 'photo_index' not in st.session_state:
    st.session_state.photo_index = 0
if 'config_actual' not in st.session_state:
    st.session_state.config_actual = None
if 'modo_busqueda' not in st.session_state:
    st.session_state.modo_busqueda = None
if 'criterio_busqueda' not in st.session_state:
    st.session_state.criterio_busqueda = None
if 'anio_filtro' not in st.session_state:
    st.session_state.anio_filtro = None


# --- 3. FUNCIÓN DE CARGA Y PROCESAMIENTO DE DATOS ---

@st.cache_data(ttl=3600)
def load_excel_from_gcs(file_name, _fs):
    """Carga un solo archivo Excel desde GCS."""
    st.info(f"Cargando {file_name}...")
    try:
        gcs_path = f"{BUCKET_NAME}/{file_name}"
        with _fs.open(gcs_path, 'rb') as f:
            data = f.read()
        
        df = pd.read_excel(io.BytesIO(data), engine='openpyxl')
        
        # Mantenemos la conversión a mayúsculas de los encabezados (columnas)
        df.columns = df.columns.str.strip().str.upper() 

        # Verificación de columnas clave para evitar KeyErrors
        required_cols = ['DESCRIPCION', 'AÑO', 'NOMBRE']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            st.error(f"Error Crítico: Faltan las columnas: {', '.join(missing_cols)} en el archivo {file_name}.")
            st.warning(f"Columnas encontradas después de la normalización: {df.columns.tolist()}")
            return pd.DataFrame()
            
        st.success(f"Excel '{file_name}' cargado correctamente.")
        return df
    except FileNotFoundError:
        st.error(f"Error: Archivo '{file_name}' no encontrado en el Bucket '{BUCKET_NAME}'.")
    except Exception as e:
        st.error(f"Error al cargar el archivo Excel '{file_name}': {e}")
    return pd.DataFrame()

def cargar_y_unificar_por_orden(orden_claves, _fs, _cache):
    """Implementa la lógica de Tkinter para cargar, unificar y ordenar DataFrames."""
    df_list = []
    family_order_map = {key: i for i, key in enumerate(orden_claves)}
    
    for key in orden_claves:
        config = consultas_individuales.get(key)
        if not config: continue
        
        excel_name_key = config["ruta_excel"].upper() 
        
        # Cargar o obtener de la caché
        if excel_name_key not in _cache:
            _cache[excel_name_key] = load_excel_from_gcs(config["ruta_excel"], _fs)

        df_original = _cache[excel_name_key]
        if df_original.empty: continue

        # Procesar el DataFrame (Esta lógica es necesaria para que la app funcione)
        temp_df = df_original.copy()
        temp_df['_FOLDER_PATH'] = GCS_BASE_PATH.rstrip('/') + '/' + config["carpeta_fotos"].lstrip('/') 
        temp_df['_ORDER_INDEX'] = family_order_map[key]
        temp_df['AÑO_NUM'] = pd.to_numeric(temp_df['AÑO'], errors='coerce')
        # ⚠️ Línea crítica: La columna NOMBRE_FOTO es necesaria para el visor
        temp_df['NOMBRE_FOTO'] = temp_df['NOMBRE'].astype(str).str.strip() 
        df_list.append(temp_df)

    if not df_list:
        st.error("No se pudo cargar ningún archivo de Excel para la consulta global.")
        return None

    combined_df = pd.concat(df_list, ignore_index=True)
    
    # ORDENAR FINAL: AÑO -> ORDEN DE CARGA/FAMILIA -> NOMBRE
    combined_df = combined_df.sort_values(
        by=['AÑO_NUM', '_ORDER_INDEX', 'NOMBRE_FOTO'], 
        ascending=[True, True, True], 
        na_position='last'
    )
    
    combined_df = combined_df.drop(columns=['AÑO_NUM', '_ORDER_INDEX']).reset_index(drop=True)
    return combined_df


# --- 4. FUNCIÓN DE FILTRADO Y NAVEGACIÓN ---

def go_home():
    """Vuelve al menú principal."""
    st.session_state.menu_state = 'INICIO'
    st.session_state.filtered_results = pd.DataFrame()
    st.session_state.photo_index = 0
    st.session_state.config_actual = None
    st.session_state.modo_busqueda = None
    st.session_state.criterio_busqueda = None
    st.session_state.anio_filtro = None

def filter_data(df, modo, criterio, anio_filtro_str):
    """Implementa la lógica de filtrado de DESCRIPCION/PERSONAJE de Tkinter."""
    
    # 1. Filtrar por Descripción/Personaje
    if modo == "D":
        # Usamos .get() y la serie "DESCRIPCION" ya normalizada
        descripcion_serie = df.get("DESCRIPCION", pd.Series("", index=df.index)) 
        
        if not criterio:
            filtered_df = df.copy()
        else:
            filtered_df = df[descripcion_serie.astype(str).str.contains(criterio, case=False, na=False)]
    else: # Modo "P" (Personaje)
        if not criterio:
            return pd.DataFrame()
            
        # Buscar en todas las columnas que contengan 'PERSONAJE'
        columnas_personaje = [col for col in df.columns if "PERSONAJE" in col]
        filtro = pd.Series(False, index=df.index)
        for col in columnas_personaje:
            filtro |= df[col].astype(str).str.contains(criterio, case=False, na=False)
        filtered_df = df[filtro]
        
    if filtered_df.empty:
        return pd.DataFrame()

    # 2. Filtrar por Año (Lógica compleja de Tkinter)
    if anio_filtro_str:
        try:
            anio_filtro_int = int(anio_filtro_str.strip())
            
            # 1. Columna numérica temporal para el filtro
            anio_serie = filtered_df.get("AÑO", pd.Series(None, index=filtered_df.index))
            filtered_df['AÑO_FILTRO_NUM'] = pd.to_numeric(anio_serie.astype(str).str.strip(), errors='coerce')
            
            # 2. Buscar el año más bajo disponible que sea mayor o igual al solicitado
            siguiente_anio_val = filtered_df[filtered_df['AÑO_FILTRO_NUM'] >= anio_filtro_int]['AÑO_FILTRO_NUM'].min()
            
            if pd.notna(siguiente_anio_val):
                anio_encontrado = int(siguiente_anio_val)
                # 3. Aplicar el filtro final
                filtered_df = filtered_df[filtered_df['AÑO_FILTRO_NUM'] >= anio_encontrado]
                
                if anio_encontrado > anio_filtro_int:
                    st.warning(f"Filtro ajustado: No se encontraron fotos disponibles a partir del año {anio_filtro_int}. Mostrando resultados a partir del año {anio_encontrado} (el más próximo encontrado).")
            else:
                filtered_df = pd.DataFrame()

            # 4. Eliminar columna temporal
            if not filtered_df.empty:
                filtered_df = filtered_df.drop(columns=['AÑO_FILTRO_NUM'])

        except ValueError:
            st.warning("El valor del año no es un número. Se ignorará el filtro de año.")
    
    # En modo individual, si se filtró por año, se necesita ordenar por año.
    if st.session_state.opcion_elegida in consultas_individuales and anio_filtro_str and filtered_df.shape[0] > 0:
        anio_sort_serie = filtered_df.get("AÑO", pd.Series(None, index=filtered_df.index))
        filtered_df['AÑO_ORDEN'] = pd.to_numeric(anio_sort_serie, errors='coerce')
        filtered_df = filtered_df.sort_values(by='AÑO_ORDEN', ascending=True, na_position='last')
        filtered_df = filtered_df.drop(columns=['AÑO_ORDEN']).reset_index(drop=True)

    return filtered_df.reset_index(drop=True)


def update_index(direction):
    """Cambia la foto actual (Izquierda/Derecha)."""
    new_index = st.session_state.photo_index + direction
    if 0 <= new_index < len(st.session_state.filtered_results):
        st.session_state.photo_index = new_index
    # Re-ejecutar la app para mostrar la nueva foto
    st.rerun()


# --- 5. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide", page_title="Visor Familiar Cloud")
st.title("Álbum Familiar Digital 📸 (Web)")

# 5.1. Carga inicial de datos
for key, config in consultas_individuales.items():
    excel_name_key = config["ruta_excel"].upper()
    if excel_name_key not in st.session_state.df_cache:
        # Carga silenciosa
        st.session_state.df_cache[excel_name_key] = load_excel_from_gcs(config["ruta_excel"], fs)

# 5.2. Lógica del Menú Principal
if st.session_state.menu_state == 'INICIO':
    st.header("Seleccione una Consulta")
    
    # Crear dos columnas para consultas individuales y globales
    col_ind, col_global = st.columns([1, 1])

    with col_ind:
        st.subheader("Consultas Individuales")
        for key, config in consultas_individuales.items():
            if st.button(f"{key} - {config['nombre']}", key=f"btn_{key}"):
                st.session_state.config_actual = config
                st.session_state.opcion_elegida = key
                df_temp = st.session_state.df_cache[config["ruta_excel"].upper()]
                
                if not df_temp.empty:
                    # ⚠️ Lógica crítica: Crear las columnas de la ruta y la foto (necesario para que la app no se rompa)
                    df_base = df_temp.copy()
                    df_base['_FOLDER_PATH'] = GCS_BASE_PATH.rstrip('/') + '/' + config["carpeta_fotos"].lstrip('/') 
                    df_base['NOMBRE_FOTO'] = df_base['NOMBRE'].astype(str).str.strip() 
                    
                    st.session_state.df_base = df_base 
                    st.session_state.menu_state = 'MODO_BUSQUEDA'
                    st.rerun()

    with col_global:
        st.subheader("Consultas Globales")
        for key, config in consultas_globales.items():
            if st.button(f"{key} - {config['nombre']}", key=f"btn_{key}"):
                st.session_state.config_actual = config
                st.session_state.opcion_elegida = key
                
                # Cargar y unificar DataFrames (esta función ya crea NOMBRE_FOTO)
                st.session_state.df_base = cargar_y_unificar_por_orden(
                    config['orden_carga'], fs, st.session_state.df_cache
                )
                if st.session_state.df_base is not None and not st.session_state.df_base.empty:
                    st.session_state.menu_state = 'MODO_BUSQUEDA'
                st.rerun()
                
    st.sidebar.markdown("Presione el botón para empezar.")

# 5.3. Selección de Modo de Búsqueda (D o P)
elif st.session_state.menu_state == 'MODO_BUSQUEDA':
    st.header(f"Consulta: {st.session_state.config_actual['nombre']} (Modo: {'DESCRIPCIÓN' if st.session_state.modo_busqueda == 'D' else 'PERSONAJE'})")
    
    st.warning("Seleccione D para DESCRIPCIÓN o P para PERSONAJE:")
    
    col_d, col_p, col_volver = st.columns([1, 1, 1])
    
    if col_d.button("D - DESCRIPCIÓN"):
        st.session_state.modo_busqueda = "D"
        st.session_state.menu_state = 'FILTRAR'
        st.rerun()
    
    if col_p.button("P - PERSONAJE"):
        st.session_state.modo_busqueda = "P"
        st.session_state.menu_state = 'FILTRAR'
        st.rerun()

    if col_volver.button("⬅️ Volver al Menú"):
        go_home()
        st.rerun()

# 5.4. Interfaz de Filtrado (Criterio y Año)
elif st.session_state.menu_state == 'FILTRAR':
    st.header(f"Filtrar: {st.session_state.config_actual['nombre']} (Modo: {'DESCRIPCIÓN' if st.session_state.modo_busqueda == 'D' else 'PERSONAJE'})")
    
    st.session_state.criterio_busqueda = st.text_input("Ingrese palabra o nombre clave (Vacío para ver todo en modo D):")
    st.session_state.anio_filtro = st.text_input("Ingrese un año para filtrar (dejar en blanco para ver todas):")

    col_filtrar, col_cambiar_modo, col_volver = st.columns([1, 1, 1])

    if col_filtrar.button("🔍 Buscar"):
        # Asegurarse de que al menos en modo P haya un criterio
        if st.session_state.modo_busqueda == "P" and not st.session_state.criterio_busqueda:
            st.error("Debe ingresar una palabra para buscar por PERSONAJE.")
        else:
            # Ejecutar el filtrado
            st.session_state.filtered_results = filter_data(
                st.session_state.df_base,
                st.session_state.modo_busqueda,
                st.session_state.criterio_busqueda,
                st.session_state.anio_filtro
            )

            if st.session_state.filtered_results.empty:
                st.warning("❌ No se encontró ninguna imagen que coincida con el criterio.")
            else:
                st.session_state.photo_index = 0
                st.session_state.menu_state = 'VER_FOTO'
                st.rerun()
    
    if col_cambiar_modo.button("🔄 Cambiar Modo (D/P)"):
        st.session_state.menu_state = 'MODO_BUSQUEDA'
        st.rerun()

    if col_volver.button("⬅️ Volver al Menú"):
        go_home()
        st.rerun()


# 5.5. Visualización de Foto y Navegación
elif st.session_state.menu_state == 'VER_FOTO':
    
    df = st.session_state.filtered_results
    index = st.session_state.photo_index
    total_photos = len(df)
    
    row = df.iloc[index]
    
    # 1. Determinar rutas
    opcion_elegida = st.session_state.opcion_elegida
    # Esta línea requiere que NOMBRE_FOTO exista, por eso la lógica anterior es crítica
    nombre_archivo = str(row["NOMBRE_FOTO"]).strip() 
    
    # Usamos .get() para obtener la descripción
    descripcion = str(row.get("DESCRIPCION", "")).strip() 

    if opcion_elegida in consultas_individuales:
        # Usa la carpeta del Excel individual
        ruta_carpeta = consultas_individuales[opcion_elegida]["carpeta_fotos"]
    else:
        # Usa la carpeta del DataFrame combinado
        # Obtenemos solo el nombre de la carpeta (ej: FOTOSCO)
        ruta_carpeta = row['_FOLDER_PATH'].split('/')[-1]
    
    # URL completa de GCS
    photo_path = GCS_BASE_PATH.rstrip('/') + '/' + ruta_carpeta + '/' + nombre_archivo
    
    # 2. Mostrar datos de la foto
    st.subheader(f"Foto {index + 1} de {total_photos} - {st.session_state.config_actual['nombre']}")
    
    # Preparar metadatos (Personajes y Año)
    personajes = []
    for col in df.columns:
        if "PERSONAJE" in col:
            valor = row.get(col)
            if pd.notna(valor) and str(valor).strip() != "":
                personajes.append(str(valor).strip())
                
    # Usamos .get() para obtener el año
    anio_valor = row.get("AÑO")
    anio_foto = ""
    if pd.notna(anio_valor) and str(anio_valor).strip() != "":
        try:
            # Asegurar que el año se muestra como un entero
            anio_foto = str(int(float(str(anio_valor).strip()))).strip()
        except:
            pass
            
    # 3. Mostrar imagen o error
    try:
        ext = os.path.splitext(nombre_archivo)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
            # Cargar imagen desde GCS
            with fs.open(photo_path, 'rb') as f:
                image_data = f.read()
                
            # 🟢 ÚNICA CORRECCIÓN DE TAMAÑO SOLICITADA:
            col_izq, col_img, col_der = st.columns([1, 4, 1]) 
            
            with col_img:
                st.image(image_data, caption=nombre_archivo, use_container_width=True) 
            
        elif ext in ['.mp4', '.avi', '.mov', '.mkv']:
            st.warning("⚠️ Archivo es un video. Haga clic derecho -> Guardar para descargar y ver.")
            st.markdown(f"**Archivo de video:** `{nombre_archivo}`")
            
        else:
            st.error(f"Tipo de archivo no soportado: {ext}")

    except FileNotFoundError:
        st.error(f"⚠️ Error: Archivo de foto '{nombre_archivo}' no encontrado en la nube. (Ruta generada: {photo_path})")
    except Exception as e:
        st.error(f"Error al cargar la foto: {e}")

    # 4. Mostrar Metadatos
    st.markdown("---")
    
    # Mostrar Año y Personajes en columnas
    col_meta1, col_meta2 = st.columns([1, 4])
    col_meta1.metric(label="Año", value=anio_foto if anio_foto else "Desconocido")
    
    if personajes:
        col_meta2.markdown(f"**Personajes:** {', '.join(personajes)}")

    # Mostrar Descripción
    if descripcion:
        st.info(f"**Descripción:** {descripcion}")
    
    # 5. Botones de Navegación
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)

    if col1.button("⏪ Anterior"):
        update_index(-1)
    
    if col2.button("Siguiente ⏩"):
        update_index(1)

    if col3.button("🔄 Reiniciar Búsqueda"):
        st.session_state.menu_state = 'FILTRAR'
        st.session_state.photo_index = 0
        st.rerun()

    if col4.button("🏠 Volver al Menú Principal"):
        go_home()
        st.rerun()