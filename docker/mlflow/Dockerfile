# Servidor MLflow del proyecto (registro de experimentos y modelos)
FROM python:3.11-slim
# sqlalchemy<2.1: MLflow 2.22.5 falla con SQLAlchemy 2.1
RUN pip install --no-cache-dir "mlflow==2.22.5" "sqlalchemy>=2.0,<2.1"
EXPOSE 5000
