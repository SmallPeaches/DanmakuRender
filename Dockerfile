FROM python:3.9-alpine

WORKDIR /app

COPY . .

RUN apk add --no-cache nodejs ffmpeg && \
    pip install -r requirements.txt

ENTRYPOINT ["python3", "-u", "main.py"]
