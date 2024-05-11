import os
import hashlib
from datetime import datetime 
import json

from flask.views import MethodView
from flask import jsonify, request
from flask import current_app
from flask_jwt_extended import get_jwt_identity

from app.services.authentication import custom_jwt_required
from app.services.admin import log_request


class ChatView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity() 
        
        users_cursor = current_app.db.users.find({}, {'_id': False, 'password': False})
        users = list(users_cursor)
        for user in users:
            messages = current_app.db.messages.find_one({'user_id':user['uuid']}, {'_id':0, 'messages': 1})
            user["chats"] = messages if messages else None
            pipeline = [
                {
                    "$match": {
                        "user_id": user['uuid']
                    }
                },
                {
                    "$unwind": "$messages"
                },
                {
                    "$match": {
                        "messages.is_seen": False, 
                        "messages.is_response":False
                    }
                },
                {
                    "$group": {
                        "_id": "$_id",
                        "user_id": { "$first": "$user_id" },
                        "messages": { "$push": "$messages" }
                    }
                }
            ]

            unseen_messages = list(current_app.db.messages.aggregate(pipeline))
            
            if unseen_messages:
                user["unseen_msg"] = unseen_messages[0]
                del user['unseen_msg']['_id']
                user["latest_chat"] = unseen_messages[0]['messages'][-1]
            else:
                user["unseen_msg"] = None
                user["latest_chat"] = None 
        
        return jsonify(users), 200


class UpdateChatStatus(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request(request)
        current_user = get_jwt_identity() 
       
        data = request.json
        email = data.get('email')
        user = current_app.db.users.find_one({'email': email})
        current_app.db.messages.update_many(
            {'user_id': user['uuid'], 'messages.is_response': False},
            {'$set': {'messages.$[elem].is_seen': True}},
            array_filters=[{'elem.is_response': False}]
        )
        return jsonify({"message":"successfully updated!"}), 200


class SaveAdminResponseView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        from app import mqtt_client
        log_request(request)
        current_user = get_jwt_identity()

        data = request.json 
        message_id = data.get('message_id')
        message = data.get('message')
        user_id = data.get('user_id')

        user = current_app.db.users.find_one({'uuid':user_id})

        if not message_id or not message or not user:
            return jsonify({"error": "Missing session_id or message or user_id"}), 200

        mqtt_topic = f"user_chat/{user['email']}"
        mqtt_client.subscribe(mqtt_topic)

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(data)
        )

        mqtt_client.unsubscribe(mqtt_topic)

        return jsonify({"message": "Response received and published successfully"}), 200
