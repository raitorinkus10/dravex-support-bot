#!/bin/bash
gunicorn -w 1 -b 0.0.0.0:$PORT -k uvicorn.workers.UvicornWorker bot:app