FROM python:3.10-slim

WORKDIR /app

COPY alldebrid.py . 
RUN pip install requests bencodepy beautifulsoup4

CMD ["python", "alldebrid.py"]
