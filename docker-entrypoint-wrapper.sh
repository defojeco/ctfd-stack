#!/bin/sh
set -e

# URL-encode DB_PASSWORD safely
if command -v python3 >/dev/null 2>&1; then
  enc_pw=$(python3 -c "import os,urllib.parse; print(urllib.parse.quote_plus(os.environ.get('DB_PASSWORD','')))")
else
  # fallback minimal encoder for common chars
  enc_pw=$(echo -n "${DB_PASSWORD}" | sed -e 's/%/%25/g' -e 's/ /%20/g' -e 's/\\/\\%5C/g' -e 's/\"/%22/g' -e "s/#/%23/g" -e "s/\\$/%24/g" -e "s/&/%26/g" -e "s/+/%2B/g" -e "s/,/%2C/g" -e "s/:/%3A/g" -e "s/;/%3B/g" -e "s/=/%3D/g" -e "s/?/%3F/g" -e "s/@/%40/g" -e "s/\\//%2F/g")
fi

export DATABASE_URL="mysql+pymysql://${DB_USER}:${enc_pw}@${DB_HOST}:3306/${DB_NAME}"

# optional: dump the DATABASE_URL for debugging (comment out in production)
# echo "DATABASE_URL=${DATABASE_URL}"

exec /opt/CTFd/docker-entrypoint.sh
