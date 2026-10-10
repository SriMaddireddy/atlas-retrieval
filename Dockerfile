FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m atlas && mkdir /app/data && chown atlas:atlas /app/data
COPY atlas ./atlas
COPY static ./static
COPY data_seed ./data_seed
USER atlas
ENV HOST=0.0.0.0 PORT=8092 ATLAS_DB=/app/data/atlas.db OPENBLAS_NUM_THREADS=1
EXPOSE 8092
CMD ["python", "-m", "atlas.server"]
