import json
import os
from datetime import datetime
from bson import ObjectId
from flask.views import MethodView
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from email_validator import validate_email, EmailNotValidError
import werkzeug

from flask import current_app, url_for
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required , log_action


class SaveUserMessageView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        from app import mqtt_client

        log_request()
        data = request.form
        message = data.get('message', None)
        file = request.files.get('media_file', None)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not message and not file:
            return jsonify({'message': "Missing message content"})
        
        chat_message = {
            'user_id': user['uuid'],
            'message_content': 
                {
                    'message_id': user['uuid'],
                    'is_response': False,
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
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
                os.makedirs(user_media_dir, exist_ok=True)
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))
                chat_message['message_content']['media'] = media_url
                document_data = {
                    'name': filename,
                    'url': media_url,
                    'type': "chat",
                    'uploaded_at': datetime.now()
                }
               
                # Update the uploaded_documents collection
                current_app.db.users_uploaded_docs.update_one(
                    {'uuid': user['uuid']},
                    {'$push': {'uploaded_documents': document_data}},
                    upsert=True
                )
            else:
                # Handle the case where the file has an invalid extension
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 200
        

       
        mqtt_topic = f"user_chat/{user['email']}"
        mqtt_client.subscribe(mqtt_topic)
              
        mqtt_client.publish(
                topic=mqtt_topic,
                payload=json.dumps(chat_message)
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
       
        log_action(user['uuid'], user['role'], "customer_service-send_message", chat_message)
        return jsonify({"message": "Message received and published successfully"}), 200


class CheckResponseView(MethodView):

    decorators=[custom_jwt_required()]

    def get(self):
        log_request()
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
            log_action(user['uuid'], user['role'], "viewed-customer_service-chat", None)
            return jsonify(response), 200
        else:
            return jsonify({"response": "No response found!"}), 200


class BuyerSellersChatView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self, property_id, user_id):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 200

        seller = current_app.db.property_seller_transaction.find_one({'seller_id': user_id, 'property_id': property_id})
        
        if seller:
            buyer_id = user['uuid']
            seller_id = user_id
        else:
            seller_id = user['uuid']
            buyer_id = user_id
        
        # Retrieve messages between the buyer and seller
        messages = current_app.db.buyer_seller_messaging.find_one({
            'buyer_id': buyer_id,
            'seller_id': seller_id,
            'property_id': property_id
        })

        if not messages:
            return jsonify({'error': 'No messages found'}), 200
        
        payload ={"property_id":property_id, "receiver_id":user_id}
        
        log_action(user['uuid'], user['role'], "viewed-buyer-seller-chat", payload)
        return jsonify(messages['message_content']), 200
    

    def post(self):
        from app import mqtt_client
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 200
        
        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 200

        # Extract receiver_id and message_content from request data
        data = request.form
        receiver_id = data.get('receiver_id')
        property_id = data.get('property_id')
        message = data.get('message')
        file = request.files.get('media_file')

        if not message and not file :
            return jsonify({"error": "Missing message content"}), 200

        if not receiver_id or not property_id:
            return jsonify({"error": "Missing receiver_id or property_id"}), 200
        
        receiver = current_app.db.users.find_one({'uuid': receiver_id})
        property = current_app.db.properties.find_one({'_id': ObjectId(property_id)})

        if not receiver or not property:
            return jsonify({"error": "Receiver or property not found'"}), 200
        
        # Construct chat message document
        chat_message = {
            'property_id': property_id,
            'message_content': [
                {
                    'msg_id': user['uuid']
                }
            ],
            'key' : 'buyer_seller_messaging'
        }

        seller = current_app.db.property_seller_transaction.find_one({'seller_id': receiver_id, 'property_id': property_id})
        
        if seller:
            buyer_id = user['uuid']
            seller_id = receiver_id
            topic_email = current_app.db.users.find_one({'uuid': seller_id}, {'email':1, '_id': 0})['email'] + f'/{property_id}/{buyer_id}'
        else:
            buyer_id = receiver_id
            seller_id = user['uuid']
            topic_email = user['email'] + f'/{property_id}/{buyer_id}'
        
        chat_message['buyer_id'] = buyer_id
        chat_message['seller_id'] = seller_id  
 
        if message:
            chat_message['message_content'][0]['message']  = message
        
        if file and werkzeug.utils.secure_filename(file.filename):
            # Check if the file has an allowed extension
            allowed_extensions = {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}
            if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                org_filename = werkzeug.utils.secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{org_filename}"
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
                os.makedirs(user_media_dir, exist_ok=True)
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))
                chat_message['message_content'][0]['media'] = media_url
                document_data = {
                    'name': filename,
                    'url': media_url,
                    'type': "chat",
                    'uploaded_at': datetime.now()
                }

                # Update the uploaded_documents collection
                current_app.db.users_uploaded_docs.update_one(
                    {'uuid': user['uuid']},
                    {'$push': {'uploaded_documents': document_data}},
                    upsert=True
                )
            else:
                # Handle the case where the file has an invalid extension
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 200

        if buyer_id == seller_id:
            return jsonify({"error": "Only buyers for this property can chat"}), 200
              
        mqtt_topic = f"buyer_seller_chat/{topic_email}"
        mqtt_client.subscribe(mqtt_topic)

        # Publish the message to the MQTT topic
        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )
        
        mqtt_client.unsubscribe(mqtt_topic)
        
        log_action(user['uuid'], user['role'], "buyer_seller_chat-send_message", chat_message)
        return jsonify({'message': 'Message sent successfully'}), 200


class ChatUsersListView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 200

        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 200

        receivers = list(current_app.db.buyer_seller_messaging.find({'buyer_id': user['uuid']}, {'property_id': 1, 'seller_id': 1, '_id': 0}))
        if len(receivers) != 0:
            for receiver in receivers:
                seller = current_app.db.users.find_one({'uuid': receiver['seller_id']}, {'email': 1, 'first_name': 1, 'profile_pic': 1, '_id': 0})
                property_address = current_app.db.properties.find_one({'_id': ObjectId(receiver['property_id'])}, {'address': 1, '_id': 0})
                if property_address:
                    receiver['property_address'] = property_address['address']
                else:
                    receiver['property_address'] = None
                receiver['owner_email'] = seller.get('email') if seller else None
                receiver['first_name'] = seller.get('first_name') if seller else None
                receiver['profile_pic'] = seller.get('profile_pic') if seller else None
                receiver['user_id'] = receiver.pop('seller_id')
               
            log_action(user['uuid'], user['role'], "viwed-chat_users", None)
            return jsonify(receivers), 200
        else: 
            seller_id = user['uuid']
            receivers = list(current_app.db.buyer_seller_messaging.find({'seller_id': seller_id}, {'property_id': 1, 'buyer_id': 1, '_id': 0}))
            for receiver in receivers:
                buyer = current_app.db.users.find_one({'uuid': receiver['buyer_id']}, {'email': 1,'first_name': 1,  'profile_pic': 1, '_id': 0})
                property_address = current_app.db.properties.find_one({'_id': ObjectId(receiver['property_id'])}, {'address': 1, '_id': 0})
                if property_address:
                    receiver['property_address'] = property_address['address']
                else:
                    receiver['property_address'] = None
                receiver['email'] = buyer.get('email') if buyer else None
                receiver['first_name'] = buyer.get('first_name') if buyer else None
                receiver['profile_pic'] = buyer.get('profile_pic') if buyer else None
                receiver['user_id'] = receiver.pop('buyer_id')
            
            log_action(user['uuid'], user['role'], "viwed-chat_users", None)    
            return jsonify(receivers), 200
