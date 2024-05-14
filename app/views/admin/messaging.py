import os
import hashlib
from datetime import datetime 
import json

from flask.views import MethodView
from flask import jsonify, request
from flask import current_app , url_for
from flask_jwt_extended import get_jwt_identity
import werkzeug

from app.services.authentication import custom_jwt_required, log_action
from app.services.admin import log_request


class ChatView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity() 
        user = current_app.db.users.find_one({'email': current_user})
        
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
        log_action(user['uuid'], user['role'], "viewed-chats", None)
        return jsonify(users), 200


class UpdateChatStatus(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request()
        current_user = get_jwt_identity() 
        logged_in_user = current_app.db.users.find_one({'email': current_user})
        
        data = request.json
        email = data.get('email')
        user = current_app.db.users.find_one({'email': email})
        current_app.db.messages.update_many(
            {'user_id': user['uuid'], 'messages.is_response': False},
            {'$set': {'messages.$[elem].is_seen': True}},
            array_filters=[{'elem.is_response': False}]
        )
        log_action(logged_in_user['uuid'],logged_in_user['role'],"viewed-message", data)
        return jsonify({"message":"successfully updated!"}), 200


class SaveAdminResponseView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        from app import mqtt_client
        log_request()
        current_user = get_jwt_identity()
        logged_in_user = current_app.db.users.find_one({'email': current_user})

        data = request.form 
        message_id = logged_in_user['uuid']
        message = data.get('message', None)
        file = request.files.get('media_file', None)
        user_id = data.get('user_id')

        user = current_app.db.users.find_one({'uuid':user_id})

        if not user:
            return jsonify({"error": "user not found"}), 200
        
        if not message and not file:
            return jsonify({'message': "Missing message content"})
        
        chat_message = {
            'user_id': user['uuid'],
            'message_content': 
                {
                    'message_id': message_id,
                    'is_response': True,
                    'is_seen': False   
                }
        }

        if message:
            chat_message['message_content']['message'] = message

        if file and werkzeug.utils.secure_filename(file.filename):
            # Check if the file has an allowed extension
            allowed_extensions = {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}
            if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                org_filename = werkzeug.utils.secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{org_filename}"
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'] ,'customer-support-chat',logged_in_user['uuid'],'uploaded_docs', str(user['uuid']))
                os.makedirs(user_media_dir, exist_ok=True)
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('customer-support-chat',logged_in_user['uuid'],'uploaded_docs', str(user['uuid']), filename))
                chat_message['message_content']['media'] = media_url
                document_data = {
                    'name': filename,
                    'url': media_url,
                    'type': "chat",
                    'uploaded_at': datetime.now()
                }
               
                # Update the uploaded_documents collection
                current_app.db.users_uploaded_docs.update_one(
                    {'uuid': logged_in_user['uuid']},
                    {'$push': {'uploaded_documents': document_data}},
                    upsert=True
                )
            else:
                # Handle the case where the file has an invalid extension
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 200
        
        mqtt_topic = f"user_chat/{user['email']}"
        mqtt_client.subscribe(mqtt_topic)

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )

        mqtt_client.unsubscribe(mqtt_topic)
        
        log_action(logged_in_user['uuid'],logged_in_user['role'], "responded-chat", chat_message)
        return jsonify({"message": "Response received and published successfully"}), 200
