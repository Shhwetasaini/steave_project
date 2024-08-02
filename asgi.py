import os
from asgiref.wsgi import WsgiToAsgi
from app import create_app

config_name = os.getenv('CONFIG', 'development')
app = create_app(config_name)

asgi_app = WsgiToAsgi(app)
