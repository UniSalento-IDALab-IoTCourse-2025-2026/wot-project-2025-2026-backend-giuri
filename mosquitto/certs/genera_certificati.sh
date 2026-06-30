#!/bin/bash
set -e

mkdir -p mosquitto/certs
cd mosquitto/certs

# 1. CA self-signed
if [ ! -f ca.key ]; then
    openssl genrsa -out ca.key 2048
    openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
        -subj "//C=IT/O=CardioSense/CN=CardioSense-CA"
fi

# 2. Chiave + CSR del server
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "//C=IT/O=CardioSense/CN=localhost"

# 3. Creazione del file di estensione per includere i SAN (FONDAMENTALE per HTTPS)
echo "subjectAltName = DNS:localhost, IP:127.0.0.1" > server.ext

# 4. Firma del certificato server con la CA includendo le estensioni SAN
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 3650 -extfile server.ext

# Pulizia
rm server.csr server.ext
echo "Certificati corretti autogenerati con SAN in mosquitto/certs/"