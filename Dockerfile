FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl gnupg unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY load_rock_to_bigquery.py .
RUN pip install pyodbc pandas google-cloud-bigquery db-dtypes

ENTRYPOINT ["python", "load_rock_to_bigquery.py"]
