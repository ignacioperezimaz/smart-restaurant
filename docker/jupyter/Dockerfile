# Imagen de Jupyter para el proyecto: incluye pandas, numpy, scikit-learn, matplotlib...
# (vienen en scipy-notebook) y añade lo necesario para hablar con HDFS y escribir Parquet.
FROM quay.io/jupyter/scipy-notebook:python-3.11

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
