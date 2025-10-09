# Usa una imagen base con Python
FROM python:3.10-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia los archivos de requerimientos y Python
COPY requirements.txt .
COPY visor_web_2.py .  <-- ESTA LÍNEA DEBE SER CORRECTA

# Instala las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# El comando de inicio que ejecuta Streamlit
# Cloud Run usa $PORT para el puerto de escucha
CMD ["streamlit", "run", "visor_web_2.py", "--server.port", "8080", "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"]
