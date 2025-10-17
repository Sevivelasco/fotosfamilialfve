import streamlit as st
import pandas as pd
import gcsfs
import io
import os
import time

# --- 0. CSS PARA OCULTAR, AJUSTAR ESPACIO Y HEADER FLOTANTE (VERSIÓN MÍNIMA Y AGRESIVA) ---
hide_streamlit_style = """
<style>
/* Oculta el menú de 3 puntos (hamburguesa) y el pie de página ("Made with Streamlit") */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* --- CORRECCIÓN FINAL PARA LA MÁXIMA MINIMIZACIÓN DEL ESPACIO SUPERIOR --- */

/* Contenedor principal de la aplicación Streamlit */
.stApp {
    padding-top: 0px !important; 
}

/* El contenedor principal de contenido y el tag section.main */
.block-container, section.main {
    padding-top: 0rem !important; 
    padding-bottom: 0rem;
    padding-left: 1rem;
    padding-right: 1rem;
    margin-top: 0rem !important; /* Asegurar que no haya margen superior */
}

/* ---------------------------------------------------- */
/* CORRECCIONES DE ESPACIADO DE LOS METADATOS Y CONTADOR */
/* ---------------------------------------------------- */

/* Controla el espacio del contador (Foto 1 de XX) que es un st.subheader (h3) */
h3 {
    margin-top: 0.5rem !important; /* Mínimo espacio arriba del contador */
    margin-bottom: 0.5rem !important; /* Mínimo espacio debajo del contador */
}

/* Reduce el padding superior e inferior de la columna de la imagen (la que contiene la foto) */
.element-container:nth-child(4) > div { 
    padding-top: 0rem !important;
    padding-bottom: 0rem !important;
}

/* Estilo para la línea divisoria --- */
hr {
    margin-top: 0.5rem !important; /* Reduce espacio superior de la línea (entre Foto y Personajes) */
    margin-bottom: 0.5rem !important; /* Reduce espacio inferior de la línea */
}

/* Reduce el margen de los párrafos de Personajes y Archivo */
.stMarkdown > div > p {
    margin-bottom: 0.2rem !important; /* Reduce espacio entre Personajes y Nombre */
}

/* IMPORTANTE: EL ESTILO .final-description YA NO ES NECESARIO AQUÍ YA QUE EL TEXTO VA EN LA FOTO */
.final-description {
    text-align: center;
    font-size: 1.1rem;
    font-weight: bold;
    margin: 0px !important; 
    padding: 0px !important;
    width: 100%;
    visibility: hidden; 
    height: 0px; 
}


/* ---------------------------------------------------- */
/* ESTILOS DE NAVEGACIÓN Y ENCABEZADO */
/* ---------------------------------------------------- */

.sticky-header {
    position: sticky;
    top: 0; 
    z-index: 1000; 
    background-color: white; 
    padding: 0.1rem 1rem 0.1rem 0rem;
    border-bottom: 1px solid #ccc;
    margin-bottom: 0;
    display: flex; 
    align-items: center;
    justify-content: space-between;
    min-height: 20px; 
    line-height: 1.2; 
}
.header-text {
    font-size: 1.0rem; 
    color: #333;
    margin: 0;
    line-height: 1.2;
}
.header-description {
    flex-grow: 1; 
    font-weight: bold;
    padding-right: 20px; 
}
.header-anio {
    flex-shrink: 0;
    min-width: 50px; 
    text-align: right;
    font-weight: bold;
}

/* CSS para que los botones de navegación sean más pequeños y juntos */
.stButton>button {
    font-size: 0.8rem !important; 
    padding: 0.2rem 0.5rem !important; 
    line-height: 1 !important;
}

</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
# ---------------------------------------------


# --- 1. CONFIGURACIÓN DE NUBE (GCS) ---

# ⚠️ Importante: Nombre de tu Bucket en Google Cloud Storage
BUCKET_NAME = "fotosfamilialfve"
# La ruta base de las fotos en tu Bucket
GCS_BASE_PATH = f"gs://{BUCKET_NAME}/"
CACHE_TTL = 3600 # Variable para el TTL (Time To Live) del caché (1 hora)

# Inicialización del FileSystem de GCS
@st.cache_resource
def init_gcs_fs():
    """Inicializa la conexión a GCS (requiere autenticación de gcloud)."""
    try:
        fs = gcsfs.GCSFileSystem()
        return fs
    except Exception as e:
        return None

fs = init_gcs_fs()
if not fs:
    st.error("Error al inicializar GCS FileSystem. Verifique la configuración de su llave JSON o permisos.")
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


# --- 2. GESTIÓN DEL ESTADO Y DATOS (INICIALIZACIÓN) ---

if 'menu_state' not in st.session_state: st.session_state.menu_state = 'INICIO' 
if 'df_cache' not in st.session_state: st.session_state.df_cache = {} 
if 'filtered_results' not in st.session_state: st.session_state.filtered_results = pd.DataFrame()
if 'photo_index' not in st.session_state: st.session_state.photo_index = 0
if 'config_actual' not in st.session_state: st.session_state.config_actual = None
if 'opcion_elegida' not in st.session_state: st.session_state.opcion_elegida = None
if 'modo_busqueda' not in st.session_state: st.session_state.modo_busqueda = None
if 'criterio_busqueda' not in st.session_state: st.session_state.criterio_busqueda = None
if 'anio_filtro' not in st.session_state: st.session_state.anio_filtro = None


# --- 3. FUNCIÓN DE CARGA Y PROCESAMIENTO DE DATOS ---
@st.cache_data(ttl=CACHE_TTL)
def load_excel_from_gcs(file_name, _fs):
    """Carga un solo archivo Excel desde GCS."""
    try:
        gcs_path = f"{BUCKET_NAME}/{file_name}"
        with _fs.open(gcs_path, 'rb') as f:
            data = f.read()
            
        df = pd.read_excel(io.BytesIO(data), engine='openpyxl')
        
        df.columns = df.columns.str.strip().str.upper()

        required_cols = ['DESCRIPCION', 'AÑO', 'NOMBRE']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            st.error(f"Error Crítico: Faltan las columnas: {', '.join(missing_cols)} en el archivo {file_name}.")
            st.warning(f"Columnas encontradas después de la normalización: {df.columns.tolist()}")
            return pd.DataFrame()
            
        return df
    except FileNotFoundError:
        st.error(f"Error: Archivo '{file_name}' no encontrado en el Bucket '{BUCKET_NAME}'.")
    except Exception as e:
        st.error(f"Error al cargar el archivo Excel '{file_name}': {e}")
    return pd.DataFrame()

@st.cache_data(ttl=CACHE_TTL)
def cargar_y_unificar_por_orden(orden_claves, _fs, _cache):
    """Implementa la lógica de Tkinter para cargar, unificar y ordenar DataFrames."""
    df_list = []
    family_order_map = {key: i for i, key in enumerate(orden_claves)}
    
    for key in orden_claves:
        config = consultas_individuales.get(key)
        if not config: continue
        
        excel_name_key = config["ruta_excel"].upper()
        
        if excel_name_key not in _cache:
            _cache[excel_name_key] = load_excel_from_gcs(config["ruta_excel"], _fs)

        df_original = _cache[excel_name_key]
        if df_original.empty: continue

        temp_df = df_original.copy()
        temp_df['_FOLDER_PATH'] = GCS_BASE_PATH.rstrip('/') + '/' + config["carpeta_fotos"].lstrip('/')
        temp_df['_ORDER_INDEX'] = family_order_map[key]
        temp_df['AÑO_NUM'] = pd.to_numeric(temp_df['AÑO'], errors='coerce')
        temp_df['NOMBRE_FOTO'] = temp_df['NOMBRE'].astype(str).str.strip()
        df_list.append(temp_df)

    if not df_list:
        st.error("No se pudo cargar ningún archivo de Excel para la consulta global.")
        return None

    combined_df = pd.concat(df_list, ignore_index=True)
    
    combined_df = combined_df.sort_values(
        by=['AÑO_NUM', '_ORDER_INDEX', 'NOMBRE_FOTO'],
        ascending=[True, True, True],
        na_position='last'
    )
    
    combined_df = combined_df.drop(columns=['AÑO_NUM', '_ORDER_INDEX']).reset_index(drop=True)
    return combined_df


# --- 4. FUNCIÓN DE FILTRADO Y NAVEGACIÓN ---

def go_home():
    """Vuelve al menú principal (Selección de Consulta)."""
    st.session_state.menu_state = 'INICIO'
    st.session_state.filtered_results = pd.DataFrame()
    st.session_state.photo_index = 0
    st.session_state.config_actual = None
    st.session_state.modo_busqueda = None
    st.session_state.criterio_busqueda = None
    st.session_state.anio_filtro = None
    st.rerun()

def go_to_filter():
    """Vuelve al menú de filtrado."""
    st.session_state.menu_state = 'FILTRAR'
    st.session_state.photo_index = 0
    st.rerun()

def filter_data(df, modo, criterio, anio_filtro_str):
    """Implementa la lógica de filtrado de DESCRIPCION/PERSONAJE de Tkinter."""
    
    # 1. Filtrar por Descripción/Personaje
    if modo == "D":
        descripcion_serie = df.get("DESCRIPCION", pd.Series("", index=df.index))
        
        if not criterio:
            filtered_df = df.copy()
        else:
            filtered_df = df[descripcion_serie.astype(str).str.contains(criterio, case=False, na=False)]
    else: # Modo "P" (Personaje)
        if not criterio:
            return pd.DataFrame()
            
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
            
            anio_serie = filtered_df.get("AÑO", pd.Series(None, index=filtered_df.index))
            filtered_df['AÑO_FILTRO_NUM'] = pd.to_numeric(anio_serie.astype(str).str.strip(), errors='coerce')
            
            siguiente_anio_val = filtered_df[filtered_df['AÑO_FILTRO_NUM'] >= anio_filtro_int]['AÑO_FILTRO_NUM'].min()
            
            if pd.notna(siguiente_anio_val):
                anio_encontrado = int(siguiente_anio_val)
                filtered_df = filtered_df[filtered_df['AÑO_FILTRO_NUM'] >= anio_encontrado]
                
                if anio_encontrado > anio_filtro_int:
                    st.warning(f"Filtro ajustado: No se encontraron fotos disponibles a partir del año {anio_filtro_int}. Mostrando resultados a partir del año {anio_encontrado} (el más próximo encontrado).")
            else:
                filtered_df = pd.DataFrame()

            if not filtered_df.empty:
                filtered_df = filtered_df.drop(columns=['AÑO_FILTRO_NUM']) 

        except ValueError:
            st.warning("El valor del año no es un número. Se ignorará el filtro de año.")
    
    if st.session_state.opcion_elegida in consultas_individuales and anio_filtro_str and filtered_df.shape[0] > 0:
        anio_sort_serie = filtered_df.get("AÑO", pd.Series(None, index=filtered_df.index))
        filtered_df['AÑO_ORDEN'] = pd.to_numeric(anio_sort_serie, errors='coerce')
        filtered_df = filtered_df.sort_values(by='AÑO_ORDEN', ascending=True, na_position='last')
        filtered_df = filtered_df.drop(columns=['AÑO_ORDEN']).reset_index(drop=True)

    return filtered_df.reset_index(drop=True)


def update_index(direction): 
    """
    Cambia la foto actual con navegación circular.
    """
    total = len(st.session_state.filtered_results)
    if total == 0:
        return

    new_index = st.session_state.photo_index + direction
    
    if new_index >= total:
        st.session_state.photo_index = 0
    elif new_index < 0:
        st.session_state.photo_index = total - 1
    else:
        st.session_state.photo_index = new_index
        
    st.rerun()


# --- 5. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide", page_title="Visor Familiar Cloud")

# 5.1. Carga inicial de datos (para cache)
for key, config in consultas_individuales.items():
    excel_name_key = config["ruta_excel"].upper()
    if excel_name_key not in st.session_state.df_cache:
        st.session_state.df_cache[excel_name_key] = load_excel_from_gcs(config["ruta_excel"], fs)

# 5.2. Lógica del Menú Principal (INICIO)
if st.session_state.menu_state == 'INICIO':
    st.subheader("Seleccione una Consulta") 
    
    col_ind, col_global = st.columns([1, 1])

    with col_ind:
        st.markdown("### Consultas Individuales")
        for key, config in consultas_individuales.items():
            if st.button(f"{key} - {config['nombre']}", key=f"btn_{key}"):
                st.session_state.config_actual = config
                st.session_state.opcion_elegida = key
                df_temp = st.session_state.df_cache[config["ruta_excel"].upper()]
                
                if not df_temp.empty:
                    df_base = df_temp.copy()
                    df_base['_FOLDER_PATH'] = GCS_BASE_PATH.rstrip('/') + '/' + config["carpeta_fotos"].lstrip('/')
                    df_base['NOMBRE_FOTO'] = df_base['NOMBRE'].astype(str).str.strip()
                    
                    st.session_state.df_base = df_base
                    st.session_state.menu_state = 'MODO_BUSQUEDA'
                    st.rerun()

    with col_global:
        st.markdown("### Consultas Globales")
        for key, config in consultas_globales.items():
            if st.button(f"{key} - {config['nombre']}", key=f"btn_{key}"):
                st.session_state.config_actual = config
                st.session_state.opcion_elegida = key
                
                st.session_state.df_base = cargar_y_unificar_por_orden(
                    config['orden_carga'], fs, st.session_state.df_cache
                )
                if st.session_state.df_base is not None and not st.session_state.df_base.empty:
                    st.session_state.menu_state = 'MODO_BUSQUEDA'
                st.rerun()
                
    st.sidebar.markdown("Presione el botón para empezar.")

# 5.3. Selección de Modo de Búsqueda (MODO_BUSQUEDA)
elif st.session_state.menu_state == 'MODO_BUSQUEDA':
    st.subheader(f"Consulta: {st.session_state.config_actual['nombre']}") 
    
    st.markdown(f"**Modo Actual: {'DESCRIPCIÓN' if st.session_state.modo_busqueda == 'D' else 'PERSONAJE'}**")
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

# 5.4. Interfaz de Filtrado (FILTRAR)
elif st.session_state.menu_state == 'FILTRAR':
    st.subheader(f"Filtrar: {st.session_state.config_actual['nombre']} (Modo: {'DESCRIPCIÓN' if st.session_state.modo_busqueda == 'D' else 'PERSONAJE'})") 
    
    st.session_state.criterio_busqueda = st.text_input("Ingrese palabra o nombre clave (Vacío para ver todo en modo D):")
    st.session_state.anio_filtro = st.text_input("Ingrese un año para filtrar (dejar en blanco para ver todas):")

    col_filtrar, col_cambiar_modo, col_volver = st.columns([1, 1, 1])
    
    if col_filtrar.button("🔍 Buscar (Ver Fotos)"):
        if st.session_state.modo_busqueda == "P" and not st.session_state.criterio_busqueda:
            st.error("Debe ingresar una palabra para buscar por PERSONAJE.")
        else:
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

# 5.5. Visualización de Foto y Navegación (VER_FOTO)
elif st.session_state.menu_state == 'VER_FOTO':
    
    df = st.session_state.filtered_results
    index = st.session_state.photo_index
    total_photos = len(df)
    
    if total_photos == 0:
        st.warning("No hay resultados para mostrar.")
        if st.button("Volver al Filtro"):
            st.session_state.menu_state = 'FILTRAR'
            st.rerun()
        st.stop()

    row = df.iloc[index]
    
    # 1. Determinar rutas y metadatos
    opcion_elegida = st.session_state.opcion_elegida
    nombre_archivo = str(row["NOMBRE_FOTO"]).strip()
    descripcion = str(row.get("DESCRIPCION", "")).strip()

    if opcion_elegida in consultas_individuales:
        ruta_carpeta = consultas_individuales[opcion_elegida]["carpeta_fotos"]
    else:
        ruta_carpeta = row['_FOLDER_PATH'].split('/')[-1]
    
    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{ruta_carpeta}/{nombre_archivo}"
    
    # Obtener metadatos
    personajes = []
    for col in df.columns:
        if "PERSONAJE" in col:
            valor = row.get(col)
            if pd.notna(valor) and str(valor).strip() != "":
                personajes.append(str(valor).strip())
                
    anio_valor = row.get("AÑO")
    anio_foto = ""
    if pd.notna(anio_valor) and str(anio_valor).strip() != "":
        try:
            anio_foto = str(int(float(str(anio_valor).strip()))).strip()
        except:
            pass
            
    # 2. ENCABEZADO FLOTANTE (STICKY) - SE MANTIENE EL CÓDIGO
    descripcion_header_val = descripcion if descripcion else "*No disponible*"
    descripcion_header = f"Descripción: {descripcion_header_val}"
    anio_header = f"{anio_foto}" if anio_foto else "*Desconocido*"
    
    html_header_content = f"""
    <div class="sticky-header">
        <p class="header-text header-description">{descripcion_header}</p>
        <p class="header-text header-anio">{anio_header}</p>
    </div>
    """
    st.markdown(html_header_content, unsafe_allow_html=True)
            
    # 3. Definir Columnas para IMAGEN y NAVEGACIÓN
    col_img, col_nav_next = st.columns([8, 1]) 
    
    try:
        ext = os.path.splitext(nombre_archivo)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
            
            # --- PREPARACIÓN DEL TEXTO PARA LA SUPERPOSICIÓN ---
            descripcion_mostrar = descripcion.strip() if descripcion.strip() else ""
            anio_mostrar = f" ({anio_foto})" if anio_foto else ""
            
            texto_superpuesto = f"{descripcion_mostrar}{anio_mostrar}"

            # --- CÓDIGO HTML/CSS para ESCALADO INTELIGENTE Y SUPERPOSICIÓN EN LA FOTO ---
            html_img_code = f"""
            <div style="
                position: relative; 
                height: 90vh; /* <--- CAMBIO CLAVE: Usa 98% de la altura de la ventana */
                display: flex; 
                align-items: flex-start;
                justify-content: left; 
                overflow: hidden;
            ">
                <img src="{public_url}" style="
                    max-width: 100%; 
                    max-height: 100%; 
                    object-fit: contain; 
                    display: block;
                ">
                <div style="
                    position: absolute; /* Superposición */
                    bottom: 0; 
                    left: 50%; /* Centra el div */
                    transform: translateX(-50%); /* Ajuste de centrado */
                    max-width: 100%; 
                    width: max-content; 
                    min-width: 20%; 
                    background: rgba(0, 0, 0, 0.7); 
                    color: white; 
                    padding: 8px 15px;
                    font-size: 1.1rem;
                    font-weight: bold;
                    text-align: center;
                    border-radius: 5px 5px 0 0; 
                    box-sizing: border-box;
                ">
                    {texto_superpuesto if texto_superpuesto else "*Información no disponible*"}
                </div>
            </div>
            """
            
            with col_img:
                st.markdown(html_img_code, unsafe_allow_html=True)
            
            # --- BOTONES DE NAVEGACIÓN (Pequeños y Juntos) ---
            with col_nav_next:
                
                # Espacio para alinear verticalmente con la imagen
                st.markdown('<div style="height: 50px;"></div>', unsafe_allow_html=True) 
                
                # 1. Botón Anterior (ANT)
                if st.button("⬅️ ANT", key="btn_prev"):
                    update_index(-1)
                    
                # 2. Botón Siguiente (SIG)
                if st.button("SIG ➡️", key="btn_next"):
                    update_index(1)
                    
                st.markdown('<div style="height: 50px;"></div>', unsafe_allow_html=True) 

                # 3. Botón Volver/Menú
                if st.button("🏠 MENÚ", key="btn_volver_filtro"):
                    go_home() 
            
        elif ext in ['.mp4', '.avi', '.mov', '.mkv']:
            with col_img:
                st.warning("⚠️ Archivo es un video. Haga clic derecho -> Guardar para descargar y ver.")
                st.markdown(f"**Archivo de video:** `{nombre_archivo}`")
        else:
            with col_img:
                st.error(f"Tipo de archivo no soportado: {ext}")

    except Exception as e:
        with col_img:
            st.error(f"Error al cargar la foto: {e}")

    # 4. Mostrar Metadatos INFERIORES (Personajes y Nombre de Archivo)
    st.markdown("---")
    
    col_data, col_vacia = st.columns([9, 1])

    with col_data:
        
        # PERSONAJES
        st.markdown(f"**PERSONAJES:** {', '.join(personajes)}" if personajes else "**PERSONAJES:** *No disponibles*")
            
        # NOMBRE DE ARCHIVO
        st.markdown(f"**NOMBRE DE ARCHIVO:** `{nombre_archivo}`")
        
    st.markdown("---")
    
    # 5. Contador (Al final) - MANTENIDO Y CON ESPACIO CORREGIDO
    st.subheader(f"Foto {index + 1} de {total_photos} - {st.session_state.config_actual['nombre']}")
