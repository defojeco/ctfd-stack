FROM ctfd/ctfd:3.8.5
USER root
RUN pip install ldap3>=2.9 cryptography>=41.0
# copy entrypoint wrapper into image and make executable
COPY docker-entrypoint-wrapper.sh /usr/local/bin/docker-entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-wrapper.sh
USER ctfd
