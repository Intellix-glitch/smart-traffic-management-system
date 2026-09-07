# Smart Traffic AI — Docker image
# Use this with any Docker host (Render Docker, Railway, Fly.io, Hugging Face Spaces, ...)
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_DEBUG=0

# Install CPU-only PyTorch first (the default PyPI wheel pulls ~3 GB of CUDA
# libs we don't need), then the app requirements.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "backend/app.py"]