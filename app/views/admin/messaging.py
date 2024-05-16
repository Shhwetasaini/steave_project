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
        current_app.db.messages.update_one(
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


class SavePropertyAdminResponseView(MethodView):
    decorators=[custom_jwt_required()]

    def get(self,  property_id, user_id):
        log_request()
        current_user = get_jwt_identity()
        admin_user = current_app.db.users.find_one({'email': current_user})
        user = current_app.db.users.find_one({'uuid': user_id})
        
        if not user or not admin_user:
            return jsonify({"error": "User not found!"}), 200

        #updating message status
        current_app.db.users_customer_service_property_chat.update_one(
            {'user_id': user_id, 'property_id': property_id, 'message_content.is_response': False},
            {'$set': {'message_content.$[elem].is_seen': True}},
            array_filters=[{'elem.is_response': False}]
        )
        
        # Retrieve messages from MongoDB for the given user_id
        message_document = current_app.db.users_customer_service_property_chat.find_one({
            'user_id': user['uuid'],  
            'property_id':property_id 
        }, {'_id': 0})

        if message_document:
            response = message_document['message_content']   #[message['message'] for message in messages]
            log_action(admin_user['uuid'], admin_user['role'], "viewed-customer_service-property-chat", {'property_id':  property_id, 'user_id':user_id})
            return jsonify(response), 200
        else:
            return jsonify({"response": "No response found!"}), 200

    def post(self):
        from app import mqtt_client
        
        log_request()

        data = request.form
        property_id = data.get('property_id')
        user_id = data.get('user_id')
        property_address = data.get('property_address')
        message = data.get('message',None)
        file = request.files.get('media_file',None)
        current_user = get_jwt_identity()
        
        user_admin = current_app.db.users.find_one({'email': current_user})
        user = current_app.db.users.find_one({'uuid': user_id})
 
        if not property_id or not property_address:
            return jsonify({"error": "Missing property id or property address"}), 400
        
        if not message and not file:
            return jsonify({'message': "Missing message content"}), 400
        
       
        chat_message = {
            'user_id': user_id,
            'property_id': property_id,
            'property_address': property_address,
            'message_content': [
                {
                    'message_id': user_admin['uuid'],
                    'is_response': True,
                    'is_seen': False,
                }
            ],   
            'key':'user-customer_service-property-chat'     
        }
        
        if message:
            chat_message['message_content'][0]['message'] = message

        if file and werkzeug.utils.secure_filename(file.filename):
            # Check if the file has an allowed extension
            allowed_extensions = {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}
            if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                org_filename = werkzeug.utils.secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{org_filename}"
                admin_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'customer_support_property_chat_docs',str(user_admin['uuid']), 'uploaded_docs' , user['uuid'])
                os.makedirs(admin_media_dir, exist_ok=True)
                user_media_path = os.path.join(admin_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('customer_support_property_chat_docs', str(user_admin['uuid']), 'uploaded_docs', user['uuid'], filename))
                chat_message['message_content'][0]['media'] = media_url
                document_data = {
                    'name': filename,
                    'url': media_url,
                    'type': "chat",
                    'uploaded_at': datetime.now()
                }

                # Update the uploaded_documents collection
                current_app.db.users_uploaded_docs.update_one(
                    {'uuid': user_admin['uuid']},
                    {'$push': {'uploaded_documents': document_data}}
                )
            else:
                # Handle the case where the file has an invalid extension
                return jsonify({"error": "Invalid file type. Allowed files are: png, jpg, jpeg, gif, pdf, doc, docx"}), 400

        mqtt_topic = f"user_customer_service-property-chat/{user['email']}/{property_id}"
        mqtt_client.subscribe(mqtt_topic)
        
        #Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )
        mqtt_client.unsubscribe(mqtt_topic)
        log_action(user_admin['uuid'], user_admin['role'], "responded-property-chat", chat_message)
        return jsonify({"message": "Response received and published successfully"}), 400


class UserCustomerPropertyChatUsersListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
      
        if not user:
            return jsonify({'error': 'User not found'}), 200

        receivers = list(current_app.db.users_customer_service_property_chat.find({},{'_id': 0}).sort('_id', -1))
        
        if len(receivers) != 0:  
            for receiver in receivers:
                chat_user = current_app.db.users.find_one({'uuid': receiver['user_id']})
                if not chat_user:
                    return jsonify({'error': 'Chat user not found'}), 200
                
                unseen_message_count = len(list(filter(lambda msg: not msg.get("is_response") and not msg.get("is_seen"), receiver['message_content'])))
                receiver['unseen_message_count'] = unseen_message_count
                receiver['name'] = chat_user['first_name'] + ' ' + chat_user['last_name'] 
                receiver['email'] = chat_user['email']
                receiver.pop('message_content')
                
            log_action(user['uuid'], user['role'], "viwed-property-chat-users", None)
            return jsonify(receivers), 200
        return jsonify([])
