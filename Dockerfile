FROM python:3.11-slim

# Install ffmpeg for subtitle extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy app
COPY translate_subs.py /app/translate_subs.py

# Expose port
EXPOSE 7755

# Use a non-root home directory behaviour is OK; script uses ~ for output dir
CMD ["python3", "translate_subs.py"]
