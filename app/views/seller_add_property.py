# In myapp/views.py
import base64
import phonenumbers
import logging
import os
import re
import stripe
import fitz
import datetime
from geopy.geocoders import GoogleV3
from email_validator  import validate_email, EmailNotValidError

from flask import session, current_app, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app.services.authentication import custom_jwt_required
from app.services.admin import log_request
from flask.views import MethodView


from app.services.properties import (
    update_seller,
    create_property,
    generate_unique_name,
    get_client_ip,
    send_email,
    is_valid,
    validate_address
)

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = 'sk_test_51ObRVYDBozxLjRB4vlgKvA7OOJAp6WYTlOqjQJ2e1AmngXP5aiQBvVZzehDAntHcVJsj6tUi2k4kuQRWwIHcDFCd003B5WogrF'
stripe.api_key = STRIPE_SECRET_KEY




class PropertyTypeSelectionView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        log_request(request)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        data = request.json
        property_type = data.get('property_type')
        property_address = data.get('seller_address')

        if property_address.isdigit():
            return jsonify(
                {'error':'Please enter a valid address with a combination of letters and numbers, including country, state, and postal code.'}
            )

        # Check if the address contains "US" or "United States" or "États-Unis"
        if not re.search(r'\b(US|United States|USA|États-Unis|U\.S\.?)\b', property_address, flags=re.IGNORECASE):
            return jsonify({'error': 'Please enter a valid address in the United States.'})
        
        # Check if seller_property_address is present in e_sign_data and contains mn, minnesota, fl, or florida
        if not any(keyword in  property_address.lower() for keyword in ['mn', 'minnesota', 'fl', 'florida']):
            return jsonify({'error': "The address must be located in Minnesota (MN) or Florida (FL)."})
        
        valid_address = validate_address(property_address)
        if not valid_address:
            return jsonify({'error': "Invalid Address. missing country, state or postal_code"})

        session['e_sign_data'] = {
            'property_type': property_type,
            'property_address': property_address,
            'first_name': user['first_name'],
            'last_name':  user['last_name'],
            'email': user['email'],
            'phone': user['phone'],
            'user_id': user['uuid']
        }

        return jsonify({'message':'data saved in session successfully.', 'data': session['e_sign_data']})



class PropertyUploadImageView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        log_request(request)
        e_sign_data = session.get('e_sign_data')

        if not e_sign_data:
            return jsonify({'error':'Data not found in session for previous pannel.'})
        
        # Extract images from request
        images = request.files.getlist("images")
        if images:
            e_sign_data['images'] =  images

        session['e_sign_data'] = e_sign_data
        logger.info('Session data at property_image_add_view: %s', e_sign_data)

        return jsonify({'message':'data saved in session successfully.', 'data': session['e_sign_data']})



class InfosView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        log_request(request)
        e_sign_data = session.get('e_sign_data')

        if not e_sign_data:
            return jsonify({'error':'Data not found in session for previous pannel.'})
        
        data = request.json
        
        e_sign_data['first_name'] = data.get('first_name')
        e_sign_data['last_name'] = data.get('last_name')
        e_sign_data['phone'] = data.get('phone') 
        e_sign_data['email'] = data.get('email')

        print(e_sign_data, "DFFDFD")

        query = {"email": e_sign_data['email']}
        existing_user = current_app.db.users.find_one(query)
        print(existing_user, "kjkjkjk")

        try:
            parsed_number = phonenumbers.parse(e_sign_data['phone'], None)
            if not phonenumbers.is_valid_number(parsed_number):
                return jsonify({"error": "Invalid phone number."})
        except phonenumbers.phonenumberutil.NumberParseException:
            return jsonify({"error": "Invalid phone number format."})
        except ValueError:
            error = 'Invalid phone number'
            return jsonify({"error": "Invalid phone number."})
        
        formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        e_sign_data['phone'] = formatted_phone

        if existing_user:
            if existing_user['role'] != 'seller':
                return jsonify({'error':'Unauthorized access.'})
        else:
            return jsonify({'error': "User does not exist."})
  
        session['e_sign_data'] = e_sign_data
        logger.info('Session data at infos_view: %s', e_sign_data)

        return jsonify({'message':'data saved in session successfully.', 'data': session['e_sign_data']})


class SavePdfView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        e_sign_data = session.get('e_sign_data')

        if not e_sign_data:
            return jsonify({'error':'Data not found in session for previous pannel.'})
        
        template_pdf = None
        signature_pdf = None
        signature_file_path = None
        data = request.json

        try:
            signature_data = data.get('signature_data')
            _, encoded_data = signature_data.split(',', 1)
            binary_data = base64.b64decode(encoded_data)
            property_address = e_sign_data.get('property_address', '').lower()
            if 'mn' in property_address or 'minnesota' in property_address:
                template_path = '/home/local/API/seller.pdf'
            elif 'fl' in property_address or 'florida' in property_address:
                template_path = '/home/local/API/florida.pdf'
            else:
                return jsonify({'error': 'Invalid property_address.'})
            
            signer_name = f"{e_sign_data.get('first_name', '')}_{e_sign_data.get('last_name', '')}"
            folder_path = os.path.join(current_app.root_path, 'media', 'Home', 'sign')
            os.makedirs(folder_path, exist_ok=True)
            signature_file_name = f"{signer_name}_signature.png"
            signature_file_path = os.path.join(folder_path, signature_file_name)
            with open(signature_file_path, 'wb') as file:
                file.write(binary_data)
            template_pdf = fitz.open(template_path)
            signature_pdf = fitz.open(signature_file_path)
            # Debugging: Print the page count
            print("Number of pages in the template PDF:", template_pdf.page_count)
            first_page = template_pdf[0]
            first_page.insert_text((20, 20), f"User IP: {get_client_ip(request)}")
            if template_pdf.page_count >= 4:
                fifth_page = template_pdf[3]  # Adjusted page number to exist within the document's range
                rect = fitz.Rect(430, 0, 625, 850)
                fifth_page.insert_image(rect, pixmap=signature_pdf[0].get_pixmap(), keep_proportion=True)
            else:
                return jsonify({"error":"PDF does not have enough pages to insert the signature."})
            file_path = os.path.join(folder_path, generate_unique_name(folder_path, f"{signer_name}_signed_document.pdf"))
            template_pdf.save(file_path)
            print("PDF successfully saved at:", file_path)
            return jsonify({'message':'data saved in session successfully.'})
        except Exception as e:
            print("Error during PDF generation:", str(e))
            return jsonify({'error': str(e)})
        finally:
            if template_pdf:
                template_pdf.close()
            if signature_pdf:
                signature_pdf.close()
            if signature_file_path:
                os.remove(signature_file_path)
        

class CheckoutView(MethodView):
    decorators = [custom_jwt_required()]
    def post(self):
        logger.info("Checkout process initiated.")

        address_data = session.get('e_sign_data', {})
        if not address_data:
            return jsonify({'error':'Data not found in session for previous pannel.'})
        logger.info("POST request received.")

        data = request.json
        
        token = data.get('token')
        code = data.get('code')
        payment_amount = data.get('payment_amount', 99700)  # Default to $99700 if not specified

        coupon = current_app.db.coupon.find_one({'code': code})
        if coupon:
            if is_valid(coupon):
                amount = int(coupon['discount_amount'] * 100)
            else:
                amount = int(payment_amount)  # Use the payment_amount from the request
        else:
            amount = int(payment_amount)  # Use the payment_amount from the request

        logger.info(f"Token received: {token}, Amount: {amount}")

        try:
            if amount < 100 or amount > 1000000:
                return jsonify({'error':'Invalid amount'})
            
            logger.info("Amount validated.")

            charge = stripe.Charge.create(
                amount=amount,
                currency='usd',
                source=token,
                description='Seller App',
            )

            if not (charge.paid and charge.status == 'succeeded'):
                return jsonify({'error': 'Payment failed.'})
            
            logger.info("Charge created successfully.")
            logger.info(f"Address data retrieved from session: {address_data}")

            #payment_data = {
            #    'amount':amount,
            #    'session_data': address_data
            #}
#
            #current_app.db.payment.insert_one(payment_data)
            #logger.info("Payment saved successfully.")


            #seller_id = update_seller(address_data)
            #if not seller_id:
            #    return jsonify({'error': 'Seller updation failed.'})

            property_data = {
                'property_type': address_data.get('property_type'),
                'property_type': address_data.get('property_address'),
                'property_images' : address_data.get('images', None)
            }

            property= create_property(property_data)
            if not property:
                return jsonify({'error': 'Failed to create property.'})

            subject = 'Welcome to Our Platform'
            message = 'Thank you for signing up. We appreciate your business.'
            recipient_email = address_data.get('email', '')
            
            # Replace `send_email` with your actual email sending function
            status_code, headers = send_email(subject, message, recipient_email)
            if status_code == 202:
                logger.info("Email sent successfully.")
                session['e_sign_data'] = None
                return jsonify({'message': 'Property purchase succesfull.'})  # Specify the success URL
            else:
                logger.error("Failed to send email.")
                return jsonify({'error': 'Failed to send email.'})

        except stripe.error.CardError as e:
            logger.error(f"Stripe card error: {e}")
            return jsonify({'error': str(e)})

        except ValueError as ve:
            logger.error(f"Invalid amount error: {ve}")
            return jsonify({'error': str(ve)})

