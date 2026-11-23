# Imagen del dashboard (Streamlit). Se ejecuta en Linux dentro de Docker,
# así no le afecta el bloqueo de "Control de aplicaciones" de Windows.
FROM python:3.11-slim

WORKDIR /app/dashboard

# Primero las dependencias (así Docker reutiliza la caché si solo cambia el código)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# El código NO se copia: docker-compose monta el repositorio en /app,
# de modo que los cambios en dashboard/*.py se ven al recargar la página.
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
