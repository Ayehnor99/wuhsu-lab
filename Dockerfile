# Replace your Dockerfile with this hyper-optimized version
FROM kalilinux/kali-rolling

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install core infosec tools and Python ONLY (No GUI bloat)
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    ffmpeg nmap sqlmap hashcat hydra gobuster curl wget git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /opt/wuhsu-env
ENV PATH="/opt/wuhsu-env/bin:$PATH"

COPY requirements.txt .
# (Note to agent: Remove PySide6 from requirements.txt)
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/avatars /app/.wuhsu_vector_db /app/downloads/youtube

EXPOSE 8000

# Start the Gateway headless
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
