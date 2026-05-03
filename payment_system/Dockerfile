FROM python:3.11

WORKDIR /app

COPY ./payment_system/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir debugpy

CMD python utils/other/hotreload.py "payment_system/src/app.py"
