# Usa una imagen base con Python
FROM python:3.10-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de requerimientos y Python
COPY requirements.txt .
COPY visor_web.py .

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# El comando de inicio que ejecuta Streamlit (CORREGIDO)
CMD sh -c "streamlit run visor_web.py --server.port $PORT --server.enableCORS false --server.enableXsrfProtection false"
