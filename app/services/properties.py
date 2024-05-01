import hashlib
import os
import uuid
import logging

from flask import current_app, request
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To
from datetime import timezone

logger = logging.getLogger(__name__)


def update_seller(address_data):
    try:
        address_data.pop('property_type',None)
        address_data.pop('property_address',None)

        data = {
            'first_name': address_data.get('first_name'),
            'last_name': address_data.get('last_name'),
            'phone': address_data.get('phone')
        }
        current_app.db.users.find_one_and_update(
            {"email": address_data.get('email')},
            {"$set": data},
        )
        existing_user_data = current_app.db.users.find_one({"email": address_data.get('email')})
        logger.info("Seller updated successfully.")
        return existing_user_data['uuid']
      
    except Exception as e:
        logger.error(f"Error creating or updating seller: {str(e)}")
        return None


def create_property(property_data):
    try:
        data = {
            'images': [],
            'name': '',
            'status': 'For Sale',
            'address': property_data['address'],
            'state': '',
            'city': '',
            'latitude': '',
            'longitude': '',
            'beds': '',
            'baths': '',
            'kitchen': '',
            'property_type': property_data['property_type'],
            'description': '',
            'price': '',
            'size': '',
            'seller_id': property_data['seller_id'],
            'owner_name': property_data['owner_name'],
            'owner_bio': '',
            'owner_email': property_data['owner_email'],
            'owner_number': property_data['owner_number'],
            'owner_profile': '',
            'buyers':[]
        }
        current_app.db.properties.insert_one(data)
        logger.info("Property created successfully.")
        return True
    except Exception as e:
        logger.error(f"Error creating property: {str(e)}")
        return False



def send_email(subject, message, recipient):
    # Replace 'YOUR_SENDGRID_API_KEY' with your actual SendGrid API key
    sg = sendgrid.SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])

    # Set up the sender and recipient
    from_email = Email(current_app.config['MAIL_USERNAME'])  # Change to your verified sender
    to_email = To(recipient)  # Change to your recipient

    # Create a Mail object
    mail = Mail(from_email, to_email)

    # Set the email subject
    mail.subject = subject

    # Set the email content (plain text or HTML)
    mail.content = sendgrid.helpers.mail.Content("text/plain", message)  # Changed 'contents' to 'content'

    # Send an HTTP POST request to /mail/send
    response = sg.send(mail)
    
    # Return status code and headers
    return response.status_code, response.headers



def get_client_ip(request: request):
    """
    Get the client's IP address from the request object.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def generate_unique_name(folder_path, base_name):
    full_path = os.path.join(folder_path, base_name)

    if not os.path.exists(full_path):
        return base_name

    filename, file_extension = os.path.splitext(base_name)
    index = 1

    while os.path.exists(os.path.join(folder_path, f"{filename}_{index}{file_extension}")):
        index += 1

    return f"{filename}_{index}{file_extension}"


def format_phone_number(phone):
    # Check if phone is not None
    if phone is not None:
        # Remove non-numeric characters except the plus sign
        formatted_number = ''.join(filter(str.isdigit, phone))
        if not formatted_number.startswith('+'):
            formatted_number = '+' + formatted_number
        return formatted_number
    else:
        return None


def is_valid(coupon):
    """
    Check if the coupon is currently valid.
    """
    return coupon['expiration_date'] >= timezone.now().date()
