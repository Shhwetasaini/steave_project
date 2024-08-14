import os
import random
import json
import logging
from bson import ObjectId

from flask import request, current_app
from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request
from jwt.exceptions import InvalidTokenError, DecodeError

from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail as SendGridMail



def get_session_files(session_id):
    received_file = os.path.join(current_app.config['CHAT_SESSIONS_FOLDER'], f'{session_id}_received.txt')
    pending_file = os.path.join(current_app.config['CHAT_SESSIONS_FOLDER'], f'{session_id}_pending.txt')
    return received_file, pending_file

def authenticate_request():
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(" ")[1] if auth_header else ''
    return token == current_app.config['API_KEY']


def custom_jwt_required(fn=None, refresh=False,):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                    # Check for access token and handle it
                    verify_jwt_in_request()  # Example function to check JWT presence (custom implementation)
            except DecodeError:
                return jsonify({'error': 'Invalid token format'}), 401  # Unauthorized
            except InvalidTokenError:
                return jsonify({'error': 'Token has expired or invalid!'}), 401  # Unauthorized
            except Exception as e:
                if str(e) == 'Missing Authorization Header' or str(e).startswith('Bad Authorization header'):
                    return jsonify({'error': 'Authorization token is missing or invalid!'}), 401  # Unauthorized
                elif str(e) == 'Token has been revoked':
                    return jsonify({'error': 'User session has expired, please log in again.'}), 401  # Unauthorized
                
                logging.error(f"An error occurred during JWT validation: {str(e)}")
                return jsonify({'error': 'Internal Server Error'}), 500  # Internal Server Error
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def check_if_token_revoked(jwt_header, jwt_payload: dict) -> bool:
    jti = jwt_payload["jti"]
    token = current_app.db.user_token_blocklist.find_one({"jti": jti})
    return token is not None


def send_from_directory(directory, filename):
   
    safe_path = os.path.join(directory, filename)
    if not os.path.isfile(safe_path):
        return "File not found", 404

    from flask import send_file
    return send_file(safe_path)


def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp_via_email(email, otp, subject):
    message = SendGridMail(
        from_email=current_app.config['MAIL_USERNAME'],
        to_emails=email,
        subject= subject,
        plain_text_content=f'Your OTP is: {otp}')

    try:
        sg = SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])
        response = sg.send(message)
        print(response.status_code)
    except Exception as e:
        print(str(e))



def log_action(user_id, user_role, action, payload=None):
   # Check if the user exists in the notifications collection
    existing_user_log = current_app.db.audit.find_one({"user_id": user_id})

    # Construct notification document
    log = {"action" : action, "timestamp": datetime.now(), 'payload':payload}

    if existing_user_log:
      
        current_app.db.audit.update_one(
            {"user_id": user_id},
            {"$push": {"logs": log}} 
        )
    else:
        current_app.db.audit.insert_one({"user_id": user_id, "user_role": user_role, "logs": [log]}) 


def insert_liked_properties(user_uuid, liked_properties):
    try:
        values = json.loads(liked_properties)
    except json.JSONDecodeError as e:
        return {'error':f"JSON decoding error: {e}"}

    if type(values) != list:
        return {'error':'only array of values are accepted for liked_properties'} 
    if not all(isinstance(value, str) for value in values):
        return {'error': "All array elements must be strings"}
    

    # Convert property_ids to ObjectId
    try:
        object_ids = [ObjectId(value) for value in values]
    except Exception as e:
        return {'error': "Invalid ObjectId in liked_properties: " + str(e)}
    
    # Check if all property_ids exist in the properties collection
    properties_count = current_app.db.properties.count_documents({"_id": {"$in": object_ids}})
    if properties_count != len(values):
        return {'error': "Some properties does not exists in provided payload"}
    
    # Check if all property_ids exist in the property_seller_transaction_collection
    transactions_count = current_app.db.property_seller_transaction.count_documents({"property_id": {"$in": values}})
    print(transactions_count)
    if transactions_count != len(values):
        return {'error': "Some Invalid properties exists in provided payload"}   

    current_app.db.users.find_one_and_update(
        {"uuid": user_uuid},
        {"$addToSet": {"liked_properties": {"$each": values}}}
    )  

    return {'success': True}


