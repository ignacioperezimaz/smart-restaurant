# Imagen para ejecutar el dashboard de Streamlit dentro de Docker (Linux).
# Así evitamos el bloqueo de Windows (Control de aplicaciones) sobre los
# archivos binarios de pandas. El código NO se copia a la imagen: se monta
# como volumen al ejecutar, de modo que los cambios se ven al instante.
FROM python:3.12-slim

WORKDIR /app

# Solo las dependencias (se cachean: reconstruir es rápido si no cambian)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

EXPOSE 8501

# fileWatcherType=poll: detecta los cambios de archivos montados desde Windows
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--server.fileWatcherType=poll", \
     "--browser.gatherUsageStats=false"]
