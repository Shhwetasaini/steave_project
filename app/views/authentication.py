from datetime import datetime
import hashlib
import uuid
import os
import phonenumbers

from email_validator import validate_email, EmailNotValidError
from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from flask_jwt_extended import create_access_token, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required, send_otp_via_email, generate_otp
from app.views.notifications import store_notification


class RegisterUserView(MethodView):
    def post(self):
        log_request(request)

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200

        uuid_val = str(uuid.uuid4())
        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        email = data.get('email', None)
        phone = data.get('phone', None)
        facebook = data.get('facebook', None)
        gmail = data.get('gmail', None)
        linkedin = data.get('linkedin', None)
        password = data.get('password', None)
        role = data.get('role')
        if not role:
            role='seller'          #['seller' or 'buyer' or 'realtor'] , default - seller
        
        if not uuid_val or not password or not email or not phone:
            return jsonify({"error": "email or password or phone is missing!"}), 200
        
        if role not in ['seller', 'buyer', 'realtor']:
            return jsonify({"error": "Invalid user role!"}), 200
        
        # Validate email using email_validator
        try:
            validate_email(email)
        except EmailNotValidError:
            return jsonify({"error": "Invalid email format!"}), 200
        
        #validate phone number
        try:
            parsed_number = phonenumbers.parse(phone, None)
            if not phonenumbers.is_valid_number(parsed_number):
                return jsonify({"error": "Invalid phone number."}), 200
        except phonenumbers.phonenumberutil.NumberParseException:
            return jsonify({"error": "Invalid phone number format."}), 200
        except ValueError:
            error = 'Invalid phone number'
            return jsonify({"error": "Invalid phone number."}), 200
        
        formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        
        new_user = {
            'uuid': uuid_val,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone':  formatted_phone,
            'role': role,
            'facebook': facebook,
            'gmail': gmail,
            'linkedin': linkedin,
            'password': hashlib.sha256(password.encode("utf-8")).hexdigest(),
            'is_verified': False
        }
        
        query = {"$or": [{"uuid": uuid_val}, {"email": email}]}
        existing_user = current_app.db.users.find_one(query)

        if not existing_user:
            current_app.db.users.insert_one(new_user)
            otp = generate_otp()
            current_time = datetime.now()
            current_app.db.users.update_one(
                {'email': email}, 
                {'$set': {'otp': {'value': otp, 'time': current_time, 'is_used': False}}}, 
                upsert=True
            )
            send_otp_via_email(new_user['email'], otp, subject='OTP for user verification')
            return jsonify(
                {
                    'message': 'User registered successfully, OTP has been sent on email Please verify it.'
                }
            ), 200
        else:
            return jsonify({'error': 'User already exists!, please login!'}), 200


class LoginUserView(MethodView):
    def post(self):
        log_request(request)

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200

        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"error": "email or password is missing!"}), 200
        
        user = current_app.db.users.find_one({'email': email})

        if user:
            if user['is_verified'] == False:
                return jsonify({'error': 'Verify user to login!'}), 200

            encrpted_password = hashlib.sha256(password.encode("utf-8")).hexdigest()
            if encrpted_password == user['password']:
                access_token = create_access_token(identity=email)
                store_notification(
                    user_id=user['uuid'], 
                    title="Login", 
                    message="successfully logged in",
                    type="authentication"
                )
                return jsonify({"message":"User Logged in successfully!", "access_token":access_token}), 200
            else:
                return jsonify({'error': 'Email or Password is incorrect!'}), 200
        
        return jsonify({'error': 'User does not exist, please register the user!'}), 200


class UserUuidLoginView(MethodView):
    def post(self):
        log_request(request)

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200

        uuid = data.get('user_id')

        if not uuid:
            return jsonify({"error": "uuid is missing!"}), 200
    
        user = current_app.db.users.find_one({'uuid': uuid})

        if user:
            if user['is_verified'] == False:
                return jsonify({'error': 'Verify user to login!'}), 200
            
            access_token = create_access_token(identity=uuid)
            store_notification(
                user_id=user['uuid'], 
                title="Login",
                message="successfully logged in",
                type="authentication"
            )
            return jsonify({"message":"User Logged in successfully!", "access_token":access_token}), 200
        return jsonify({'error': 'User does not exist, please register the user'}), 200


class ProfileUserView(MethodView):
    decorators = [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if user:
            user.pop('_id', None)
            user.pop('password', None)
            user.pop('downloaded_documents', None)
            user.pop('uploaded_documents', None)
            user.pop('properties:', None)
            return jsonify(user), 200
        else:
            return jsonify({'error': 'Profile not found'}), 200


class UserUUIDView(MethodView):
    def post(self):
        log_request(request)

        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 400

        email = data.get('email')
        if not email:
            return jsonify({"error": "email is missing!"}), 200

        # Query MongoDB collection for users
        user = current_app.db.users.find_one({"email": email})
        if user:
            return jsonify({'uuid': user.get('uuid', None)})
        
        return jsonify({"error": "User does not exist"}), 200
        

class LogoutUserView(MethodView):
    decorators = [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        jti = get_jwt()["jti"]
        now = datetime.now()
        current_app.db.user_token_blocklist.insert_one({
            "jti": jti,
            "created_at": now,
            'user_id': user['uuid']
        })
        store_notification(
            user_id=user['uuid'], 
            title="Logout",
            message="successfully logged out",
            type="authentication"
        )
        #current_app.db.users.update_one({'email': user['email']}, {'$set': {'is_logged_in': False}})
        return jsonify({"message": "logout successfully"}), 200


class UpdateUsersView(MethodView):
    decorators = [custom_jwt_required()]
    def put(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        update_doc = {}

        # Determine content type and parse data accordingly
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
            profile_pic = request.files.get('profile_pic')
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
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200

        first_name = data.get('first_name', None)
        last_name = data.get('last_name', None)
        phone = data.get('phone', None)
        password = data.get('password', None)

        if first_name is not None and first_name.strip() != '':
            update_doc['first_name'] = first_name
        if last_name is not None and last_name.strip() != '':
            update_doc['last_name'] = last_name
        if phone is not None and phone.strip() != '':
            #validate phone number
            try:
                parsed_number = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(parsed_number):
                    return jsonify({"error": "Invalid phone number."}), 200
            except phonenumbers.phonenumberutil.NumberParseException:
                return jsonify({"error": "Invalid phone number format."}), 200
            except ValueError:
                error = 'Invalid phone number'
                return jsonify({"error": "Invalid phone number."}), 200

            formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
            update_doc['phone'] = formatted_phone
        
        if password is not None and password.strip() != '':
            update_doc['password'] = hashlib.sha256(password.encode("utf-8")).hexdigest()

        # If the update document is empty, return an error
        if not update_doc:
            return jsonify({"error": "No fields to update!"}), 200

        updated_user = current_app.db.users.find_one_and_update(
            {"uuid": user['uuid']},
            {"$set": update_doc},
            return_document=True 
        )

        if updated_user:
            store_notification(
                user_id=user['uuid'],
                title="Update", 
                message="information updated successfully",
                type="authentication"
            )
            return jsonify({'message':"User updated Successfully!"}), 200
        else:
            return jsonify({'error': 'User not found or no fields to update!'}), 200  


class ForgetPasswdView(MethodView):
    def post(self):
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200
        
        email = data.get('email') or request.form.get('email')
        if not email:
            jsonify({"error": "Email is missing!"}), 200
        
        user = current_app.db.users.find_one({'email': email})

        if user:
            otp = generate_otp()
            current_time = datetime.now()
            current_app.db.users.update_one(
                {'email': email}, 
                {'$set': {'otp': {'value': otp, 'time': current_time,  'is_used': False}}}, 
                upsert=True
            )
            send_otp_via_email(user['email'], otp, subject='OTP for Password Reset')
            return jsonify({'message': 'OTP sent to your email'}), 200
        else:
            return  jsonify(), 200


class ResetPasswdView(MethodView):
    def post(self):
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200
        
        email = data.get('email')
        otp_received = data.get('otp')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not email or not otp_received or not new_password or not confirm_password:
            return jsonify({"All fields are required"}), 200
        
        if new_password != confirm_password:
            return jsonify({"error": "Both password must be same"}), 200

        user = current_app.db.users.find_one({'email': email})       

        if user and user['otp']['value'] == otp_received:
            otp_created_at = user['otp']['time']
            current_time = datetime.now()
            time_difference = current_time - otp_created_at
            if time_difference.total_seconds() <= 3600 and user['otp']['is_used'] == False:
                hashed_password = hashlib.sha256(new_password.encode("utf-8")).hexdigest()  
                current_app.db.users.update_one({'email': email}, {'$set': {'password': hashed_password, "otp.is_used": True}})
                store_notification(
                    user_id=user['uuid'], 
                    title="Reset-password",
                    message="Password reset successfully",
                    type="authentication"
                )
                return jsonify({'message': 'password reset successfully'}), 200
            else:
                return jsonify({'message': 'OTP has used or expired'}), 200
        else:
            return jsonify({'message': 'Invalid OTP or Email'}), 200


class VerifyOtpView(MethodView):
    def post(self):
        if request.content_type.startswith('multipart/form-data'):
            data = request.form
        elif request.is_json:
            data = request.json
        else:
            return jsonify({"error": "Unsupported Content Type"}), 200
        
        email = data.get('email')
        otp_received = data.get('otp')

        user = current_app.db.users.find_one({'email': email})

        if user and user['otp']['value'] == otp_received:
            otp_created_at = user['otp']['time']
            current_time = datetime.now()
            time_difference = current_time - otp_created_at
            if time_difference.total_seconds() <= 3600:
                current_app.db.users.update_one({'email': email}, {'$set': {'is_verified': True,  "otp.is_used": True}})
                return jsonify({'message': 'OTP verification successful'}), 200
            else:
                return jsonify({'message': 'OTP has expired'}), 200
        else:
            return jsonify({'message': 'Invalid OTP or Email'}), 200
