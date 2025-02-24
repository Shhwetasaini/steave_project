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
from app.services.properties import (
    get_receivers, 
    search_messages, 
    search_customer_property_mesage,
    search_customer_service_mesage,
    send_notification, save_archived_message
)


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
            
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not message and not file:
            return jsonify({'message': "Missing message content"}), 400
        
        chat_message = {
            'user_id': user['uuid'],
            'message_content': 
               [{
                    'message_id': user['uuid'],
                    'is_response': False,
                    'is_seen': False   
                }]
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
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
                os.makedirs(user_media_dir, exist_ok=True)
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))
                chat_message['message_content'][0]['media'] = media_url
                
                document_data = {
                    'doc_id': str(ObjectId()),
                    'name': filename,
                    'sender': user.get('first_name') + " " + user.get('last_name'),
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
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 415
        

       
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
        return jsonify({"message": "Message received and published successfully"}), 201


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
      
        if not user:
            return jsonify({"error":"user not found "}), 404
        
        # Retrieve messages from MongoDB for the given user_id
        current_app.db.messages.update_one(
            {'user_id': user['uuid'], 'messages.is_response': True},
            {'$set': {'messages.$[elem].is_seen': True}},
            array_filters=[{'elem.is_response': True}]
        )
        message_document = current_app.db.messages.find_one({'user_id': user['uuid'] }, {'_id': 0})

        if message_document:
            response = message_document['messages']   #[message['message'] for message in messages]
            log_action(user['uuid'], user['role'], "viewed-customer_service-chat", {})
            return jsonify(response), 200
        else:
            return jsonify({"response": "No response found!"}), 404


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
            return jsonify({'error': 'User not found'}), 404
        
        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 403

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
            return jsonify({'error': 'No messages found'}), 404
        
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
            return jsonify({'error': 'User not found'}), 404

        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 403

        data = request.form
        receiver_id = data.get('receiver_id')
        property_id = data.get('property_id')
        message = data.get('message')
        file = request.files.get('media_file')
        archived = data.get('archived', False)  # Archived flag

        if not message and not file:
            return jsonify({"error": "Missing message content"}), 400

        if not receiver_id or not property_id:
            return jsonify({"error": "Missing receiver_id or property_id"}), 400

        receiver = current_app.db.users.find_one({'uuid': receiver_id})
        user_property = current_app.db.properties.find_one({'_id': ObjectId(property_id)})

        if not receiver or not user_property:
            return jsonify({"error": "Receiver or property not found"}), 404

        chat_message = {
            'property_id': property_id,
            'message_content': [],
            'key': 'buyer_seller_messaging',
            'archived': archived  # Adding archived flag to the message
        }

        seller = current_app.db.property_seller_transaction.find_one({'seller_id': receiver_id, 'property_id': property_id})

        if seller:
            buyer_id = user['uuid']
            seller_id = receiver_id
            topic_email = current_app.db.users.find_one({'uuid': seller_id}, {'email': 1, '_id': 0})['email'] + f'/{property_id}/{buyer_id}'
        else:
            buyer_id = receiver_id
            seller_id = user['uuid']
            topic_email = user['email'] + f'/{property_id}/{buyer_id}'

        chat_message['buyer_id'] = buyer_id
        chat_message['seller_id'] = seller_id  
        timestamp = datetime.now()
        new_message_content = {
            'msg_id': user['uuid'],
            'message': message if message else '',
            'timestamp': timestamp
        }

        if file and werkzeug.utils.secure_filename(file.filename):
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
                new_message_content['media'] = media_url
                document_data = {
                    'name': filename,
                    'sender': user.get('first_name') + " " + user.get('last_name'),
                    'property_name': user_property.get('name'),
                    'property_address': user_property.get('address'),
                    'url': media_url,
                    'type': "chat",
                    'uploaded_at': datetime.now()
                }

                current_app.db.users_uploaded_docs.update_one(
                    {'uuid': user['uuid']},
                    {'$push': {'uploaded_documents': document_data}},
                    upsert=True
                )
            else:
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 415

        if buyer_id == seller_id:
            return jsonify({"error": "Only buyers for this property can chat"}), 400

        mqtt_topic = f"buyer_seller_chat/{topic_email}"
        mqtt_client.subscribe(mqtt_topic)

        mqtt_client.publish(
            topic=mqtt_topic, 
            payload=json.dumps(chat_message)
        )

        mqtt_client.unsubscribe(mqtt_topic)

        notify = send_notification(receiver.get('device_token'))
        if notify.get('error'):
            current_app.logger.error(f"Notification Error: {notify['error']}")

        log_action(user['uuid'], user['role'], "buyer_seller_chat-send_message", chat_message)

        if archived:
            # Existing archived message check
            existing_message = current_app.db.archived_messages.find_one({
                'buyer_id': buyer_id,
                'seller_id': seller_id,
                'property_id': property_id
            })

            if existing_message:
                current_app.db.archived_messages.update_one(
                    {'_id': existing_message['_id']},
                    {'$push': {'message_content': new_message_content}}
                )
                return jsonify({'message': 'Message successfully added to archive'}), 200
            else:
                chat_message['message_content'].append(new_message_content)
                # Save the archived message to a different storage bucket/folder
                save_archived_message(chat_message)  # This method should handle saving in the separate location
                return jsonify({'message': 'Message successfully archived'}), 201
        else:
            # Existing buyer_seller_messaging message check
            existing_message = current_app.db.buyer_seller_messaging.find_one({
                'buyer_id': buyer_id,
                'seller_id': seller_id,
                'property_id': property_id
            })

            if existing_message:
                current_app.db.buyer_seller_messaging.update_one(
                    {'_id': existing_message['_id']},
                    {'$push': {'message_content': new_message_content}}
                )
                return jsonify({'message': 'Message successfully added'}), 200
            else:
                chat_message['message_content'].append(new_message_content)
                current_app.db.buyer_seller_messaging.insert_one(chat_message)
                return jsonify({'message': 'Message successfully sent'}), 201

class BuyerSellerChatUsersListView(MethodView):
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
            return jsonify({'error': 'User not found'}), 404

        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 403

        buyer_receivers = get_receivers('buyer_id', user['uuid'])
        seller_receivers = get_receivers('seller_id', user['uuid'])

        log_action(user['uuid'], user['role'], "viewed-chat_users", {})
        
        receivers = buyer_receivers + seller_receivers
        return jsonify(receivers), 200


class BuyerSellerChatSearchView(MethodView):
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
            return jsonify({'error': 'User not found'}), 404

        user_role = user.get('role')
        if user_role == 'realtor':
            return jsonify({'error': 'Unauthorized access'}), 403

        query = request.args.get('query')
        if not query:
            return jsonify({"error": "Query parameter is required"}), 400

        query_lower = query.lower()

        # Search in chat users list (first_name, last_name, email)
        buyer_receivers = get_receivers('buyer_id', user['uuid'], query_lower)
        seller_receivers = get_receivers('seller_id', user['uuid'], query_lower)
        receivers = buyer_receivers + seller_receivers
        # Search in messages
        message_results = search_messages(user['uuid'], query_lower)
        property_message_results = search_customer_property_mesage(query,  user['uuid'])
        message_results = message_results + property_message_results[0]
        receivers  = receivers + property_message_results[1]
        message_results = message_results + search_customer_service_mesage(query, user['uuid'])
        for message in message_results:
            email = message['user_details']['email']
            message_user = current_app.db.users.find_one({'email': email})
            if message_user:
                message['user_details']['user_id'] = message_user.get('uuid')


        log_action(user['uuid'], user['role'], "searched-on-chat-page", {'searched_query': query})
        return jsonify({
            'chat_users': receivers,
            'message_results': message_results
        }), 200


class UserCustomerServicePropertySendMesssageView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self,  property_id):
        log_request()
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        if not user:
            return jsonify({'error': 'User not found'}), 404
        #updating message status
        current_app.db.users_customer_service_property_chat.update_one(
            {'user_id':  user['uuid'], 'property_id': property_id, 'message_content.is_response': True},
            {'$set': {'message_content.$[elem].is_seen': True}},
            array_filters=[{'elem.is_response': True}]
        )
        
        # Retrieve messages from MongoDB for the given user_id
        message_document = current_app.db.users_customer_service_property_chat.find_one({
            'user_id': user['uuid'],  
            'property_id':property_id 
        }, {'_id': 0})

        if message_document:
            response = message_document['message_content']   #[message['message'] for message in messages]
            log_action(user['uuid'], user['role'], "viewed-customer_service-property-chat", {'property_id':  property_id})
            return jsonify(response), 200
        else:
            return jsonify({"response": "No response found!"}), 404


    def post(self):
        from app import mqtt_client

        log_request()
        data = request.form
        property_id = data.get('property_id')
        message = data.get('message', None)
        file = request.files.get('media_file', None)
        property_address = data.get('property_address', None)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
            
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not property_id or not property_address:
            return jsonify({"error": "Missing property_id or address"}), 400
        
        if not message and not file:
            return jsonify({'error': "Missing message content"}), 400
        
        user_property = current_app.db.property_seller_transaction.find_one({'property_id': property_id, 'seller_id': "Customer-Service"})
        if not user_property:
            return jsonify({"error": "Property does not exist"}), 400
        
        chat_message = {
            'user_id': user['uuid'],
            'property_id': property_id,
            'property_address': property_address,
            'message_content': [{
                'msg_id': user['uuid'],
                'is_response': False,
                'is_seen': False,
            }],
            'key': 'user-customer_service-property-chat'          
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
                user_media_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_docs', str(user['uuid']), 'uploaded_docs')
                os.makedirs(user_media_dir, exist_ok=True)
                user_media_path = os.path.join(user_media_dir, filename)
                file.save(user_media_path)
                media_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))
                chat_message['message_content'][0]['media'] = media_url
                document_data = {
                    'doc_id': str(ObjectId()),
                    'name': filename,
                    'sender': user.get('first_name') + " " + user.get('last_name'),
                    'property_name': user_property.get('name'),
                    'property_address':user_property.get('address'),
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
                return jsonify({"error": "Invalid file type. Allowed files are: {'png', 'jpg', 'jpeg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'}"}), 415
  
        mqtt_topic = f"user_customer_service_property_chat/{user['email']}/{property_id}"
        mqtt_client.subscribe(mqtt_topic)
              
        mqtt_client.publish(
                topic=mqtt_topic,
                payload=json.dumps(chat_message)
        )

        log_action(user['uuid'], user['role'], "customer_service-property-chat", chat_message)
        mqtt_client.unsubscribe(mqtt_topic)
        return jsonify({"message": "Message received and published successfully"}), 201


class UserCustomerServicePropertyChatUserList(MethodView):
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
            return jsonify({'error': 'User not found'}), 404

        receivers = list(current_app.db.users_customer_service_property_chat.find({'user_id':user['uuid']}, {'_id':0}))
        if len(receivers) != 0:
            chat_user_list = []
            for chat in receivers:
                chat_info = {
                    'property_id': chat['property_id'],
                    'property_address': chat['property_address'],
                    'name': 'Customer-Service'
                }
                chat_user_list.append(chat_info)
               
            log_action(user['uuid'], user['role'], "viwed-customer-service-property-chat-list", {})
            return jsonify(chat_user_list), 200
        else :
            return jsonify([]), 200
