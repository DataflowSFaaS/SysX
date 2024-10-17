FROM python:3.12-slim

COPY shopping-cart-demo/requirements.txt /var/local/system_x/
COPY system_x-package /var/local/system_x-package/

RUN groupadd system_x \
    && useradd -m -d /usr/local/system_x -g system_x system_x

RUN pip install --upgrade pip \
    && pip install --prefix=/usr/local -r /var/local/system_x/requirements.txt \
    && pip install --prefix=/usr/local ./var/local/system_x-package/

WORKDIR /usr/local/system_x/shopping-cart-demo

COPY --chown=system_x shopping-cart-demo .

ENV PYTHONPATH /usr/local/system_x

USER system_x

# default port
EXPOSE 5000