FROM python:3.11-slim

WORKDIR /app

COPY tracker.py view_now.py web_app.py ./

RUN mkdir -p /data

ENV HOST=0.0.0.0
ENV PORT=8000
ENV XFT_STORAGE_DIR=/data

EXPOSE 8000

CMD ["python3", "web_app.py"]
