import json
from datetime import datetime
from bson import ObjectId
from flask.views import MethodView
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from email_validator import validate_email, EmailNotValidError

from flask import current_app
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required
from app.views.notifications import store_notification


class SaveUserMessageView(MethodView):
    decorators=[custom_jwt_required()]

    def post(self):
        from app import mqtt_client

        log_request(request)

        data = request.json if request.is_json else request.form
        message = data.get('message')
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        mqtt_topic = f"user_chat/{user['email']}"
        mqtt_client.subscribe(mqtt_topic)

        if not message:
            return jsonify({"error": "Missing message"}), 200

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(
                {'user_id': user['uuid'], 'message_id': user['uuid'], 'message': message, 'is_response':False, 'is_seen': False}
            )
        )

        #url = 'http://192.168.38.100:80/api/customers/machinebuilt/'
        #payload = {
        #    "question": message
        #}
#
        #response = requests.post(url, json=payload)
#
        #if response.status_code == 200:
        #    print("Success Response:")
        #    response_message = response.json()['message']['response']
        #    print(response_message)
        #else:
        #    print("Error Response:")
        #    print(response.text, response.status_code)
#
        #mqtt_client.publish(
        #    topic=mqtt_topic, 
        #    payload=json.dumps(
        #        {'user_id': user['uuid'], 'session_id': session_id, 'message': response_message, 'is_response':True, 'is_seen': False}
        #    )
        #)

        mqtt_client.unsubscribe(mqtt_topic)
        return jsonify({"message": "Message received and published successfully"}), 200


class CheckResponseView(MethodView):

    decorators=[custom_jwt_required()]

    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        # Retrieve messages from MongoDB for the given user_id
        message_document = current_app.db.messages.find_one({'user_id': user['uuid'] }, {'_id': 0})

        if message_document:
            response = message_document['messages']   #[message['message'] for message in messages]
            return jsonify(response), 200
        else:
            return jsonify({"response": "No response found!"}), 200


class SellerPropertyChatView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self, property_id, user_id):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 200

        user_role = user.get('role')
        if user_role == 'buyer':
            buyer_id = user['uuid']
            seller_id = user_id

            authorized = current_app.db.properties.find_one({
                '_id': ObjectId(property_id),
                'buyers': buyer_id, 
                'seller_id': seller_id   
            })
        elif user_role == 'seller':
            seller_id = user['uuid']
            buyer_id = user_id

            authorized = current_app.db.properties.find_one({
                '_id': ObjectId(property_id),
                'seller_id': seller_id,
                'buyers': {'$all': [buyer_id]}
            })
        else:
            return jsonify({'error': 'Unauthorized access'}), 200
        
        if not authorized:
            return jsonify({'error': 'Unauthorized access to chat messages for this property'}), 200

        
        messages = current_app.db.seller_property_messaging.find({
            'property_id': property_id,
            'seller_id': seller_id,
            'buyer_id': buyer_id
        })


        if not messages:
            return jsonify({'error': 'No messages found'}), 200
        
        return jsonify(messages['message_content']), 200

    def post(self):
        from app import mqtt_client
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        data = request.json
        receiver_id = data.get('receiver_id')
        message_content = data.get('message')
        property_id = data.get('property_id')

        if not receiver_id or not message_content or not property_id:
            return jsonify({"error": "Missing receiver_id or message or property"}), 200
        
        # Construct chat message document
        chat_message = {
            'property_id': property_id,
            'message_content': [
                {
                    'msg_id': user['uuid'],
                    'message': message_content
                }
            ],
            'key' : 'seller_property_messaging'
        }

        user_role = user.get('role')

        if user_role == 'buyer':
            buyer_id = user['uuid']
            seller_id = receiver_id
        else:
            buyer_id = receiver_id
            seller_id = user['uuid']

        # Check if the property exists and belongs to the seller
        property_doc = current_app.db.properties.find_one({'_id': ObjectId(property_id), 'seller_id': seller_id})
        if not property_doc:
            return jsonify({'error': 'Property not found or does not belong to the seller'}), 200
        if buyer_id not in property_doc['buyers']:
            return jsonify({'error': 'Buyer not found or does not belong to the seller'}), 200
        
        chat_message['buyer_id'] = buyer_id
        chat_message['seller_id'] = seller_id  

        mqtt_topic = f"seller_property_chat/{user['email']}"
        mqtt_client.subscribe(mqtt_topic)

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )
        
        mqtt_client.unsubscribe(mqtt_topic)
    
        return jsonify({'message': 'Message sent successfully'}), 200
