FROM python:3.10-slim

ENV DETOUR_TOKEN=Tr3QVNuLRJc
ENV DETOUR_SERVER_LISTEN=tcp://0.0.0.0:3171
ENV DETOUR_CLIENT_CONNECTS=tcp://127.0.0.1:3171
ENV DETOUR_CLIENT_LISTEN=tcp://0.0.0.0:3170
ENV DETOUR_IN_DOCKER=yes

WORKDIR /app
RUN mkdir -p logs

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt
COPY detour detour

EXPOSE 3170-3171

CMD ["python", "-m", "detour.client"]