
import os
import json
from datetime import datetime

from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, current_app, url_for
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required
from bson import ObjectId


class BuyersPropertyListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
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
        if user_role != 'buyer':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        properties = list(current_app.db.properties.find())
        
        if properties:
            for property in properties:
                property['property_id'] = str(property['_id'])
                property.pop('_id', None)
            
            return jsonify(properties), 200
        else:
            return jsonify({'error': "No properties found"}), 200


class AddBuyerView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        data = request.json
        property_id = data.get('property_id')
        seller_id = data.get('seller_id')

        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        user_role = user.get('role')
        if not user_role or user_role != 'buyer':
            return jsonify({'error':'Unauthorized access'}), 200
        
        # Check if the seller exists
        seller = current_app.db.users.find_one({'uuid': seller_id, 'role': 'seller'})
        if not seller:
            return jsonify({'error': 'Seller not found'}), 200
        
        # Check if the property exists and belongs to the specified seller
        property_doc = current_app.db.properties.find_one({'_id': ObjectId(property_id), 'seller_id': seller_id})
        if not property_doc:
            return jsonify({'error': 'Property not found or does not belong to the specified seller'}), 200
        
        # Update the property to add the buyer
        current_app.db.properties.update_one(
            {'_id': ObjectId(property_id)},
            {'$addToSet': {'buyers': user['email']}}
        )
        
        return jsonify({'message': 'Buyer added to property successfully'}), 200


class BuyerAllSellersView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
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
        if user_role != 'buyer':
            return jsonify({'error': 'Unauthorized access'}), 200
        
        # Retrieve properties associated with the buyer_id
        properties = current_app.db.properties.find({'buyers': {'$in': [user['uuid']]}})

        # Initialize a set to store unique seller_ids
        seller_ids = set()

        # Extract unique seller_ids from the properties
        for property in properties:
            seller_ids.add(property['seller_id'])

        # Convert the set of seller_ids to a list if needed
        seller_ids_list = list(seller_ids)

        return jsonify(seller_ids_list), 200


class BuyerSellersChatView(MethodView):
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
        elif user_role == 'seller':
            seller_id = user['uuid']
            buyer_id = user_id
        else:
            return jsonify({'error': 'Unauthorized access'}), 200
        
        # Retrieve messages between the buyer and seller
        messages = current_app.db.buyer_seller_messaging.find_one({
            'buyer_id': buyer_id,
            'seller_id': seller_id,
            'property_id': property_id
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
        
        # Extract receiver_id and message_content from request data
        data = request.json
        receiver_id = data.get('receiver_id')
        property_id = data.get('property_id')
        message_content = data.get('message')

        if not receiver_id or not message_content:
            return jsonify({"error": "Missing receiver_id or message"}), 200
        
        receiver = current_app.db.users.find_one({'uuid': receiver_id})
        if not receiver:
            return jsonify({"error": "Receiver not found'"}), 200
        
        # Construct chat message document
        chat_message = {
            'property_id': property_id,
            'message_content': [
                {
                    'msg_id': user['uuid'],
                    'message': message_content
                }
            ],
            'key' : 'buyer_seller_messaging'
        }

        user_role = user.get('role')

        if user_role == 'buyer':
            buyer_id = user['uuid']
            seller_id = receiver_id
            topic_email = current_app.db.users.find_one({'uuid': seller_id}, {'email':1, '_id': 0})['email']
        else:
            buyer_id = receiver_id
            seller_id = user['uuid']
            topic_email = user['email']
        
        chat_message['buyer_id'] = buyer_id
        chat_message['seller_id'] = seller_id   

        if buyer_id == seller_id:
            return jsonify({"error": "Invalid User ids"}), 200
              
        mqtt_topic = f"buyer_seller_chat/{topic_email}"
        mqtt_client.subscribe(mqtt_topic)

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )
        
        mqtt_client.unsubscribe(mqtt_topic)
        
        return jsonify({'message': 'Message sent successfully'}), 200


class ChatUsersListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
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
            receivers = list(current_app.db.buyer_seller_messaging.find({'buyer_id': buyer_id}, {'property_id': 1, 'seller_id': 1, '_id': 0}))
            for receiver in receivers:
                seller_email = current_app.db.users.find_one({'uuid': receiver['seller_id']}, {'email': 1, '_id': 0})
                receiver['owner_email'] = seller_email.get('email') if seller_email else None
            return jsonify(receivers), 200

        elif user_role == 'seller':
            seller_id = user['uuid']
            receivers = list(current_app.db.buyer_seller_messaging.find({'seller_id': seller_id}, {'property_id': 1, 'buyer_id': 1, '_id': 0}))
            for receiver in receivers:
                buyer_email = current_app.db.users.find_one({'uuid': receiver['buyer_id']}, {'email': 1, '_id': 0})
                receiver['email'] = buyer_email.get('email') if buyer_email else None
            return jsonify(receivers), 200
        else:
            return jsonify({'error': 'Unauthorized access'}), 200
