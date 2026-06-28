FROM python:3.12-slim

# Fonty: prawdziwy Arial / Arial Narrow (msttcorefonts) + Liberation jako fallback —
# żeby CV renderowane przez Chromium wyglądało jak oryginał.
RUN apt-get update && \
    echo "deb http://deb.debian.org/debian bookworm contrib non-free" > /etc/apt/sources.list.d/contrib.list && \
    apt-get update && \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
    apt-get install -y --no-install-recommends \
        fontconfig fonts-liberation ttf-mscorefonts-installer && \
    fc-cache -f && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

COPY app ./app
COPY template ./template

EXPOSE 8000
# ANTHROPIC_API_KEY podawany przy uruchomieniu (-e), NIE w obrazie.
# Dane (sqlite + pdf) trwałe przez wolumen na /srv/app/data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
