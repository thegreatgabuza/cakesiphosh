import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 4
threads = 2
timeout = 120
worker_class = "sync"
accesslog = "-"
errorlog = "-"
loglevel = "info" 