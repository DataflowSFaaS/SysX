FROM python:3.12.4-slim-bookworm

#RUN apt-get update && apt-get install -y git gcc


RUN groupadd system_x \
    && useradd -m -d /usr/local/system_x -g system_x system_x

USER system_x

COPY --chown=system_x:system_x worker/requirements.txt /var/local/system_x/
COPY --chown=system_x:system_x system_x-package /var/local/system_x-package/

ENV PATH="/usr/local/system_x/.local/bin:${PATH}"

RUN pip install --upgrade pip \
    && pip install --user -r /var/local/system_x/requirements.txt \
    && pip install --user ./var/local/system_x-package/

WORKDIR /usr/local/system_x

COPY --chown=system_x:system_x worker worker

COPY --chown=system_x:system_x worker/start-worker.sh /usr/local/bin/
RUN chmod a+x /usr/local/bin/start-worker.sh

ARG epoch_size
ENV SEQUENCE_MAX_SIZE ${epoch_size}

ENV PYTHONPATH /usr/local/system_x

CMD ["/usr/local/bin/start-worker.sh"]