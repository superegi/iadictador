FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY report_templates /app/report_templates

EXPOSE 8015

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8015", "--reload"]
