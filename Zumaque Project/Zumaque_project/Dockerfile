# Usamos una imagen de Python oficial
FROM python:3.10-slim

# Evitar que Python genere archivos .pyc y asegurar que los logs se vean en tiempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instalar dependencias del sistema necesarias para SQL Server (pyodbc)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    apt-transport-https \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalamos las dependencias primero para aprovechar el cache de Docker
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN pip install gunicorn

COPY . /app

# Render usa la variable de entorno PORT, gunicorn es mejor para producción
CMD gunicorn --bind 0.0.0.0:$PORT app:app