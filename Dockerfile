FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/
COPY core/ /app/core/
COPY web/ /app/web/
COPY .env.example /app/

EXPOSE 8000

CMD ["python", "app.py"]
