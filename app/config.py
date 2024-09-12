import os
import datetime

from dotenv import load_dotenv


load_dotenv()

base_dir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    BASE_URL = os.getenv('BASE_URL')
    DB_NAME = os.getenv("DB_NAME")
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = int(os.getenv('DB_PORT'))
    DB_USER =  os.getenv('DB_USER')
    DB_PASSWD =  os.getenv('DB_PASSWD')
    DEBUG  = os.getenv('FLASK_DEBUG')
    API_KEY = os.getenv('API_KEY')
    CHAT_SESSIONS_FOLDER = os.getenv('CHAT_SESSIONS_FOLDER')
    MQTT_BROKER_ADDRESS = os.getenv('MQTT_BROKER_ADDRESS')
    MQTT_USERNAME = os.getenv('MQTT_BROKER_USERNAME')
    MQTT_PASSWD = os.getenv('MQTT_BROKER_PASSWD')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = datetime.timedelta(days=5)
    
    UPLOAD_FOLDER =  os.path.abspath('app/media')
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
    STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    GOOGLE_LOCATION_API_KEY = os.getenv('GOOGLE_LOCATION_API_KEY')
    
    @staticmethod
    def init_app(app):
        pass

class DevelopmentConfig(Config):
    FLASk_DEBUG = Config.DEBUG
    SESSION_COOKIE_SECURE = False
    #MONGO_URI = f'mongodb://{Config.DB_USER}:{Config.DB_PASSWD}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}'


class ProductionConfig(Config):
    FLASk_DEBUG = Config.DEBUG
    SESSION_COOKIE_SECURE=True
    #MONGO_URI = f'mongodb://{Config.DB_USER}:{Config.DB_PASSWD}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}
