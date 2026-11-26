# Imagen de la API (FastAPI). Parte de la MISMA imagen base que el Jupyter del proyecto, para que
# scikit-learn, pandas y numpy tengan las mismas versiones con las que se entrenaron los modelos
# (un modelo guardado con una versión de scikit-learn puede fallar o dar avisos al cargarse con otra).
# Esa imagen ya está descargada si se ha construido el Jupyter, así que no añade descarga.
FROM quay.io/jupyter/scipy-notebook:python-3.11

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /home/jovyan/api
COPY --chown=${NB_UID}:${NB_GID} app ./app
COPY --chown=${NB_UID}:${NB_GID} interfaz ./interfaz

EXPOSE 8000
# Un solo proceso: los modelos viven en memoria y se recargan con POST /modelos/recargar
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
