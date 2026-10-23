FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[ui,vision]" \
    && useradd --create-home --uid 1000 app

USER app
EXPOSE 8765

# Only answer requests for localhost (protects against DNS rebinding).
# On a server, set IMAGE_SPLITTER_ALLOWED_HOSTS to its host name, or * for any.
ENV IMAGE_SPLITTER_ALLOWED_HOSTS=localhost,127.0.0.1,::1

# Settings come from IMAGE_SPLITTER_* environment variables, e.g. IMAGE_SPLITTER_BASE_URL and IMAGE_SPLITTER_MODEL.
CMD ["image-splitter", "serve", "--host", "0.0.0.0", "--port", "8765"]
