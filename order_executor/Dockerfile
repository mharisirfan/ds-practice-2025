FROM python:3.11

WORKDIR /app

COPY ./order_executor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir debugpy

CMD python utils/other/hotreload.py "order_executor/src/app.py"
