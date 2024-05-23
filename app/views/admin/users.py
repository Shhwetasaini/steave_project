import os
import uuid
import hashlib
from datetime import datetime 
import phonenumbers
from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from flask_jwt_extended import create_access_token, get_jwt_identity
from werkzeug.utils import secure_filename

from app.services.authentication import custom_jwt_required , log_action
from app.services.admin import log_request


class TokenCheckView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        return jsonify({'message': 'Token is valid'}), 200


class DashboardView(MethodView):
    decorators =  [custom_jwt_required()]

    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        log_action(user['uuid'], user['role'], "viewed-dashboard", None)
        return jsonify({'message':'success'}), 200


class AdminRegisterUserView(MethodView):
    def post(self):
        log_request()

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 400
        
        uuid_val =  uuid_val = str(uuid.uuid4())
        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        email = data.get('email', None)
        phone = data.get('phone', None)
        facebook = data.get('facebook', None)
        gmail = data.get('gmail', None)
        role = data.get('role', None)
        linkedin = data.get('linkedin', None)
        password = data.get('password', None)
        # Validate email using email_validator
        try:
            validate_email(email)
        except EmailNotValidError:
            return jsonify({"error": "Invalid email format!"}), 400
        
        
        if not all([uuid_val, password, email, phone, first_name, last_name]):
            return jsonify({"error": "uuid, password, email, phone, first_name or last_name is missing!"}), 400
        
        if role and role != 'superuser':
            return jsonify({"error": "Invalid user role."}), 400
        
        #validate phone number
        try:
            parsed_number = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(parsed_number):
                return jsonify({"error": "Invalid phone number."}), 400
        except phonenumbers.phonenumberutil.NumberParseException:
            return jsonify({"error": "Invalid phone number format."}), 400
        except ValueError:
            error = 'Invalid phone number'
            return jsonify({"error": "Invalid phone number."}), 400
        formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        new_user = {
            'uuid': uuid_val,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'role' : role,
            'phone':  formatted_phone,
            'facebook': facebook,
            'gmail': gmail,
            'linkedin': linkedin,
            'is_verified': True,
            'profile_pic': None,
            'password': hashlib.sha256(password.encode("utf-8")).hexdigest()
        }
        query = {"$or": [{"uuid": uuid_val}, {"email": email}]}
        existing_user = current_app.db.users.find_one(query)
        if not existing_user:
            current_app.db.users.insert_one(new_user)
            new_user.pop('_id')
            log_action(new_user['uuid'], new_user['role'], "registration", new_user)  
            return jsonify({'message': 'User registered successfully'}), 200
        else:
            return jsonify({'error': 'User already exists'}), 400


class AllUserView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        log_action(user['uuid'], user['role'], "viewed-users-list", None)
        users = list(current_app.db.users.find({}, {'_id': 0, 'otp': 0}))
        return jsonify(users), 200
        

class AddUserView(MethodView):
    decorators =  [custom_jwt_required()]

    def post(self):
        log_request()

        current_user = get_jwt_identity()
        logged_in_user = current_app.db.users.find_one({'email': current_user})
        
        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 400
        
        uuid_val =  uuid_val = str(uuid.uuid4())
        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        email = data.get('email', None)
        phone = data.get('phone', None)
        facebook = data.get('facebook', None)
        gmail = data.get('gmail', None)
        role = data.get('role', None)
        linkedin = data.get('linkedin', None)
        password = data.get('password', None)
        # Validate email using email_validator
        try:
            validate_email(email)
        except EmailNotValidError:
            return jsonify({"error": "Invalid email format!"}), 400
        
        
        if not all([uuid_val, password, email, phone, first_name, last_name]):
            return jsonify({"error": "uuid, password, email, phone, first_name or last_name is missing!"}), 400
        
        if role and role != 'realtor':
            return jsonify({"error": "Invalid user role."}), 400
        
        #validate phone number
        try:
            parsed_number = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(parsed_number):
                return jsonify({"error": "Invalid phone number."}), 400
        except phonenumbers.phonenumberutil.NumberParseException:
            return jsonify({"error": "Invalid phone number format."}), 400
        except ValueError:
            error = 'Invalid phone number'
            return jsonify({"error": "Invalid phone number."}), 400
        formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        new_user = {
            'uuid': uuid_val,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'role' : role,
            'phone':  formatted_phone,
            'facebook': facebook,
            'gmail': gmail,
            'linkedin': linkedin,
            'is_verified': True,
            'profile_pic': None,
            'password': hashlib.sha256(password.encode("utf-8")).hexdigest()
        }
        query = {"$or": [{"uuid": uuid_val}, {"email": email}]}
        existing_user = current_app.db.users.find_one(query)
        if not existing_user:
            current_app.db.users.insert_one(new_user)
            new_user.pop('_id')
            log_action(logged_in_user['uuid'], logged_in_user['role'], "added-user", new_user)
            return jsonify({'message': 'User registered successfully'}), 200
        else:
            return jsonify({'error': 'User already exists'}), 400


class AdminUserLoginView(MethodView):
    def post(self):
        log_request()

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 400
        email = data.get('email')
        password = data.get('password')
        if not email or not password:
            return jsonify({"error": "email or password is missing!"}), 400
        user = current_app.db.users.find_one({'email': email})
        if user:
            if user['is_verified'] == False:
                return jsonify({'error': 'Verify user to login!'}), 200
            if user.get('role') != 'superuser':
                return jsonify({"error": "Only admin uers can login here"}), 400
            encrpted_password = hashlib.sha256(password.encode("utf-8")).hexdigest()
            if encrpted_password == user['password']:
                access_token = create_access_token(identity=email)
                log_action(user['uuid'], user['role'], "login", data)
                return jsonify({"message":"User Logged in successfully!", "access_token":access_token}), 200
            else:
                return jsonify({'error': 'Email or Password is incorrect!'}), 400
        return jsonify({'error': 'User does not exist, please register the user!'}), 400 


class EditUsersView(MethodView):
    decorators =  [custom_jwt_required()]
    def put(self):
        log_request()
        current_user = get_jwt_identity()
        
        logged_in_user = current_app.db.users.find_one({'email': current_user})
        update_doc = {}
        
        data = request.form
        email = data.get('email')
        user = current_app.db.users.find_one({'email' : email})
        
        profile_pic = request.files.get('profile_pic', None)
        if profile_pic and secure_filename(profile_pic.filename):
            filename = secure_filename(profile_pic.filename)
            user_profile_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users_profile', str(user['uuid']))
            os.makedirs(user_profile_dir, exist_ok=True)
            # Delete old profile picture if it exists
            if 'profile_pic' in user:
                old_profile_pic_path = os.path.join(user_profile_dir, user['profile_pic'].split('/')[-1])
                if os.path.exists(old_profile_pic_path):
                    os.remove(old_profile_pic_path)
            profile_pic_path = os.path.join(user_profile_dir, filename)
            profile_pic.save(profile_pic_path)
            media_url = url_for('serve_media', filename=os.path.join('users_profile', str(user['uuid']), filename))
            update_doc['profile_pic'] = media_url
        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        phone = data.get('phone', None)
        password = data.get('password', None)
        facebook = data.get('facebook', None)
        gmail = data.get('gmail', None)
        linkedin = data.get('linkedin', None)
        if first_name:
            update_doc['first_name'] = first_name
        if last_name:
            update_doc['last_name'] = last_name
        if phone:
            update_doc['phone'] = phone
        if password:
            update_doc['password'] = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if facebook:
            update_doc['facebook'] = facebook
        if gmail:
            update_doc['gmail'] = gmail
        if linkedin:
            update_doc['linkedin'] = linkedin
        if not update_doc:
            return jsonify({"message": "No fields to update!"}), 200
        updated_user = current_app.db.users.find_one_and_update(
            {"uuid": user['uuid']},
            {"$set": update_doc},
            return_document=True 
        )
        if updated_user:
            log_action(logged_in_user['uuid'], logged_in_user['role'], "updated-user", update_doc)
            return jsonify({'message':"User updated Successfully!"}), 200
        else:
            return jsonify({'error': 'User not found or no fields to update!'}), 200 
        
            

class DeleteUserView(MethodView):
    decorators =  [custom_jwt_required()]
    def delete(self):
        log_request()
        current_user = get_jwt_identity()
        user = current_app.db.users.find_one({'email': current_user})
        
        result = current_app.db.users.delete_one({'email': request.json.get('email')})
        if result.deleted_count == 1:
            log_action(user['uuid'], user['role'], user['email'], "deleted-user", {'email': request.json.get('email')})
            return jsonify({'message': 'User deleted successfully'}), 200
        else:
            return jsonify({'error': 'User not found'}), 404


class GetMediaView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request()
        current_user = get_jwt_identity()
        logged_in_user = current_app.db.users.find_one({'email': current_user})
        
        all_media = list(current_app.db.media.find({}, {'_id': 0}))
        for media in all_media:
            user = current_app.db.users.find_one({'uuid':media['user_id']})
            try:
                media['email'] = user['email']
            except TypeError:
                continue
        log_action(logged_in_user['uuid'], logged_in_user['role'], "viewed-media", None)
        return jsonify(all_media), 200


class ActionLogsView(MethodView):
    decorators = [custom_jwt_required()]

    def get(self):
        log_request()

        pipeline = [
            {
                "$project": {
                    "_id": 0,
                    "user_id": 1,
                    "user_role": 1,
                    "logs": { "$sortArray": { "input": "$logs", "sortBy": { "timestamp": -1 } } }
                }
            }
        ]

        all_logs = list(current_app.db.audit.aggregate(pipeline))
        
        # Filter logs where user does not exist
        all_logs_with_users = []
        for log in all_logs:
            user = current_app.db.users.find_one({'uuid': log['user_id']})
            if user:
                log['email'] = user.get('email')
                all_logs_with_users.append(log)
            
        return jsonify(all_logs_with_users), 200
