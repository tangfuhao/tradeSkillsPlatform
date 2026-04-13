FROM python:3.12-slim

WORKDIR /app

COPY services/agent-runner/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/agent-runner /app

EXPOSE 8100

CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "8100"]
