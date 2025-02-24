import os
import json
import datetime
import logging
from flask_cors import CORS

from flask import Flask
from pymongo import MongoClient
from flask_jwt_extended import JWTManager

from app.config import config, Config
from app.services.authentication import check_if_token_revoked, send_from_directory
import paho.mqtt.client as mqtt

jwt = JWTManager()

# MQTT client initialization and connection
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=True)
mqtt_client.username_pw_set(Config.MQTT_USERNAME, Config.MQTT_PASSWD)

def create_app(config_name):   
    app = Flask(__name__,)
    CORS(app, supports_credentials=True)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)
    
    jwt.init_app(app)
    app.logger.setLevel(logging.INFO) 

    # Set the logging level for PyMongo to ERROR
    logging.getLogger('pymongo').setLevel(logging.ERROR)

    try:
        # Connect to MongoDB
        mongo_client = MongoClient(
            app.config['DB_HOST'], 
            app.config['DB_PORT'], 
            username=app.config['DB_USER'], 
            password=app.config['DB_PASSWD']
        )
        # Get the database
        app.db = mongo_client.get_database(app.config['DB_NAME'])
    except Exception as e:
        # Log the error
        app.logger.error(f"Failed to connect to MongoDB: {e}")

    jwt.token_in_blocklist_loader(check_if_token_revoked)

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    @app.route('/media/<path:filename>')
    def serve_media(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"Connected to MQTT Broker with result code {reason_code}")


    def on_message(client, userdata, msg):
        try:
            print(f"Received message on topic {msg.topic} with payload: {msg.payload.decode()}")

            try:
                payload = json.loads(msg.payload)
                print("JSON payload successfully decoded.")

                # Debugging: Check if the key is present in the payload
                if 'key' in payload:
                    print(f"Payload key: {payload['key']}")

                if payload.get('key') == 'buyer_seller_messaging':
                    print("Processing buyer_seller_messaging payload...")
                    try:
                        payload.pop('key')
                        payload['message_content'][0]['timestamp'] = datetime.datetime.now()
                        buyer_id = payload.get('buyer_id')
                        seller_id = payload.get('seller_id')
                        property_id = payload.get('property_id')

                        existing_message = app.db.buyer_seller_messaging.find_one({
                            'buyer_id': buyer_id,
                            'seller_id': seller_id,
                            'property_id': property_id
                        })

                        if existing_message:
                            app.db.buyer_seller_messaging.update_one(
                                {'_id': existing_message['_id']},
                                {'$push': {'message_content': payload['message_content'][0]}}
                            )
                            print("Updated existing buyer_seller_messaging document.")
                        else:
                            app.db.buyer_seller_messaging.insert_one(payload)
                            print("Inserted new buyer_seller_messaging document.")
                    except Exception as e:
                        print("Error in saving buyer_seller_message:", str(e))

                elif payload.get('key') == 'user-customer_service-property-chat':
                    print("Processing user-customer_service-property-chat payload...")
                    try:
                        payload.pop('key')
                        payload['message_content'][0]['timestamp'] = datetime.datetime.now()
                        existing_document = app.db.users_customer_service_property_chat.find_one({
                            'user_id': payload['user_id'], 
                            'property_id': payload['property_id']
                        })
                        if existing_document:
                            app.db.users_customer_service_property_chat.update_one(
                                {'_id': existing_document['_id']},
                                {'$push': {'message_content': payload['message_content'][0]}}
                            )
                            print("Updated existing user-customer_service-property-chat document.")
                        else:
                            app.db.users_customer_service_property_chat.insert_one(payload)
                            print("Inserted new user-customer_service-property-chat document.")
                    except Exception as e:
                        print("Error in saving user message:", str(e))

                else:
                    print("Processing general message payload...")
                    try:
                        payload['message_content'][0]['timestamp'] = datetime.datetime.now()
                        existing_document = app.db.messages.find_one({'user_id': payload['user_id']})

                        if existing_document:
                            app.db.messages.update_one({'user_id': payload['user_id']}, {'$push': {'messages': payload['message_content'][0]}})
                            print("Updated existing message document.")
                        else:
                            messages = payload['message_content']
                            payload.pop('message_content')
                            payload['messages'] = messages
                            app.db.messages.insert_one(payload)
                            print("Inserted new message document.")
                    except Exception as e:
                        print("Error in saving user message:", str(e))
            except json.JSONDecodeError:
                print("Failed to decode JSON payload.")
        except Exception as e:
            print(f"Error in on_message: {str(e)}")
    
    
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(Config.MQTT_BROKER_ADDRESS, 1883)
    mqtt_client.loop_start()  # Start the MQTT client loop


    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'ALLOW-FROM https://papi.airebrokers.com'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    from app.routes import api_bp

    app.register_blueprint(api_bp)

    return app
