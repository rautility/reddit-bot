# Legacy headless batch image only.
# Runs main.py --headless for password/cookie multi-account jobs.
# NOT for saved Chrome debug-profile attach, agentctl queue, or day-to-day
# agent operation on a local Mac. Prefer the control plane documented in
# README.md and AGENTS.md (reddit-tool / agentctl + open-profile).
FROM python:3.11-slim

# Install Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    unzip \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run with headless mode
ENTRYPOINT ["python", "main.py", "--headless"]
