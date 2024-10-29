import os
import json
import logging
from flask_cors import CORS
from flask import Flask, send_from_directory
from pymongo import MongoClient
from flask_jwt_extended import JWTManager
from app.config import config, Config
import paho.mqtt.client as mqtt
from app.services.authentication import check_if_token_revoked  
# Initialize JWT Manager
jwt = JWTManager()

# MQTT client initialization
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(Config.MQTT_USERNAME, Config.MQTT_PASSWD)

def create_app(config_name='production'):
    app = Flask(__name__)
    CORS(app, supports_credentials=True)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    jwt.init_app(app)
    
    # Set the logging level for the Flask app
    app.logger.setLevel(logging.INFO)  # Log level for Flask application

    # Set the logging level for PyMongo to ERROR to suppress debug logs
    logging.getLogger('pymongo').setLevel(logging.ERROR)

    try:
        # Check if DB_NAME is defined
        db_name = app.config.get('DB_NAME')
        app.logger.info(f"DB_NAME from config: {db_name}")  # Debugging line

        if db_name:
            # Connect to MongoDB
            mongo_client = MongoClient(
                app.config['DB_HOST'], 
                int(app.config['DB_PORT']),  # Cast port to int
            )
            # Get the database
            app.db = mongo_client[db_name]
        else:
            raise ValueError("DB_NAME is not defined.")

    except Exception as e:
        app.logger.error(f"Failed to connect to MongoDB: {e}")

    # Load JWT revocation check
    jwt.token_in_blocklist_loader(check_if_token_revoked)

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    @app.route('/media/<path:filename>')
    def serve_media(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # MQTT connection and message handling
    def on_connect(client, userdata, flags, reason_code, properties=None):
        app.logger.info(f"Connected to MQTT Broker with result code {reason_code}")

    def on_message(client, userdata, msg):
        try:
            app.logger.info(f"Received message on topic {msg.topic} with payload: {msg.payload.decode()}")
            payload = json.loads(msg.payload)
            app.logger.info("JSON payload successfully decoded.")

            # Process the message based on the key
            if 'key' in payload:
                app.logger.info(f"Payload key: {payload['key']}")

        except json.JSONDecodeError:
            app.logger.error("Failed to decode JSON payload.")
        except Exception as e:
            app.logger.error(f"Error in on_message: {str(e)}")

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    # Check and connect to MQTT Broker
    mqtt_broker_address = Config.MQTT_BROKER_ADDRESS
    if mqtt_broker_address:
        try:
            mqtt_client.connect(mqtt_broker_address, 1883)
            mqtt_client.loop_start()
            app.logger.info(f"Connected to MQTT Broker at {mqtt_broker_address}")
        except TimeoutError:
            app.logger.error("Connection to MQTT Broker timed out.")
        except Exception as e:
            app.logger.error(f"Failed to connect to MQTT Broker: {e}")
    else:
        app.logger.error("Invalid MQTT Broker Address. Please check the configuration.")

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'ALLOW-FROM https://papi.airebrokers.com'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Import and register API blueprint
    from app.routes import api_bp
    app.register_blueprint(api_bp)

    return app
