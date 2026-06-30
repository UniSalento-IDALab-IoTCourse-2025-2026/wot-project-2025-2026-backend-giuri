#!/bin/bash
# Eseguire una volta sola, dalla root del progetto: bash mosquitto/certs/genera_certificati.sh
set -e

mkdir -p mosquitto/certs
cd mosquitto/certs

# 1. CA self-signed
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
    -subj "/C=IT/O=CardioSense/CN=CardioSense-CA"

# 2. Chiave + CSR del server (Mosquitto/FastAPI)
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "/C=IT/O=CardioSense/CN=localhost"

# 3. Firma del certificato server con la CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 3650

rm server.csr
echo "Certificati generati in mosquitto/certs/"