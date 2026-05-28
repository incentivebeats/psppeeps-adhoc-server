FROM python:3.12-slim

WORKDIR /app

COPY exporter.py /app/exporter.py

ENV ADHOC_CONTAINER=psppeeps-adhoc-server
ENV EXPORTER_HOST=0.0.0.0
ENV EXPORTER_PORT=27314
ENV LOG_TAIL=5000

EXPOSE 27314

CMD ["python3", "/app/exporter.py"]
