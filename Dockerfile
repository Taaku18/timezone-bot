FROM python:3.12 as py

FROM py as build

RUN apt update

COPY requirements.txt /
RUN pip install --prefix=/inst -U -r /requirements.txt

FROM py

COPY --from=build /inst /usr/local

WORKDIR /timezonebot
CMD ["python", "main.py"]
COPY . /timezonebot
