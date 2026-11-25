# smart-restaurant
Plataforma de Inteligencia Artificial y Big Data aplicada al sector de la restauración, centrada en el análisis del rendimiento de los platos, la segmentación de la carta, la predicción de ventas y la optimización de recursos.


## API de modelos

La carpeta [`api/`](api/README.md) contiene una API (FastAPI) que sirve los dos modelos del proyecto: el **clustering de platos** (objetivo 1) y la **predicción del tiempo de preparación** de un pedido (objetivo 2). Se arranca con `docker compose up -d --build api` desde la carpeta `docker/` y su documentación interactiva está en http://localhost:8000/docs.
