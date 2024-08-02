# Example Gunicorn configuration file

# The address and port to bind to
bind = '0.0.0.0:5090'

# The number of worker processes for handling requests
workers = 4

# Log level
loglevel = 'info'

# Path to the error log file
errorlog = '/var/log/gunicorn_error.log'
