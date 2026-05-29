FROM python:3.11-slim
WORKDIR /app
COPY radar.py config.json entrypoint.sh ./
RUN mkdir -p data logs && chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
