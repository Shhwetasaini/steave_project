
import os
import json
import werkzeug
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
        data = request.form
        receiver_id = data.get('receiver_id')
        property_id = data.get('property_id')
        message = data.get('message')
        file = request.files.get('media_file')

        print(message, file)

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
 
        if message:
            chat_message['message_content'][0]['message']  = message
        
        if file and werkzeug.utils.secure_filename(file.filename):
            # Check if the file has an allowed extension
            allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}
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
                current_app.db.users.update_one(
                    {'uuid': user['uuid']},
                    {'$push': {'uploaded_documents': document_data}}
                )
            else:
                # Handle the case where the file has an invalid extension
                return jsonify({"error": "Invalid file type. Allowed files are: png, jpg, jpeg, gif, pdf, doc, docx"}), 200

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
                seller = current_app.db.users.find_one({'uuid': receiver['seller_id']}, {'email': 1, 'first_name': 1, 'profile_pic': 1, '_id': 0})
                receiver['owner_email'] = seller.get('email') if seller else None
                receiver['first_name'] = seller.get('first_name') if seller else None
                receiver['profile_pic'] = seller.get('profile_pic') if seller else None
            return jsonify(receivers), 200

        elif user_role == 'seller':
            seller_id = user['uuid']
            receivers = list(current_app.db.buyer_seller_messaging.find({'seller_id': seller_id}, {'property_id': 1, 'buyer_id': 1, '_id': 0}))
            for receiver in receivers:
                buyer = current_app.db.users.find_one({'uuid': receiver['buyer_id']}, {'email': 1,'first_name': 1,  'profile_pic': 1, '_id': 0})
                receiver['email'] = buyer.get('email') if buyer else None
                receiver['first_name'] = buyer.get('first_name') if buyer else None
                receiver['profile_pic'] = buyer.get('profile_pic') if buyer else None
            return jsonify(receivers), 200
        else:
            return jsonify({'error': 'Unauthorized access'}), 200
