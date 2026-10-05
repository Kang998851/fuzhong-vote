# 自有服务器 Docker 部署（可选）
FROM python:3.12-slim

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p uploads data && python -c "from app import app, init_db; ctx = app.app_context(); ctx.push(); init_db()"

ENV PORT=5000
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "3"]
