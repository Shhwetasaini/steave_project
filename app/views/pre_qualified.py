import logging
from enum import Enum
from geopy.geocoders import GoogleV3
from flask import jsonify, current_app
from flask import request, jsonify, current_app
from flask.views import MethodView
from flask_jwt_extended import get_jwt_identity
from app.services.admin import log_request
from app.services.authentication import custom_jwt_required
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)



class TimelineStage(Enum):
    THINKING = "I am thinking about buying"
    LOOKING = "Touring open houses"
    FOUND_HOME = "Making offers on a property"
    REFINANCING = "I have signed a purchase contract"
    TILLTHREEMONTHS = "0-3 months"
    TILLFOURMONTHS = "4-6 months"
    SEVENPLUSMONTHS = "7+ months" 
    NOTSURE = "Not sure"

class HomeUse(Enum):
    PRIMARY = "Primary Residence"
    SECONDARY = "Secondary Residence"
    INVESTMENT = "Investment Property"
    SINGLE_FAMILY = "Single Family"
    TOWNHOUSE = "Town House"
    CONDOMINIUM = "Condominium"
    Mobile_manufactured = "Mobile or manufactured"

class EstateAgent(Enum):
    YES = "Yes"
    NO = "No"

class ForHome(Enum):
    BORROWER = "I am a borrower"
    COBORROWER = "I have a Co-borrower"

class CreditScore(Enum):
    ABOVE_720 = "720 & above"
    BETWEEN_680_719 = "660-719"
    BETWEEN_640_679 = "620-659"
    BETWEEN_600_639 = "580-619"
    BELOW_600 = "579 or below"


class PrequalView(MethodView):
    decorators=[custom_jwt_required()]
    def post(self):
        log_request()
        current_user = get_jwt_identity()
        
        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})
      
        if not user:
            return jsonify({"error": "user not found"}), 404
        
        data = request.json 
        endpoint = request.path.replace('/api', '')
        
        if endpoint == '/timeline_stage':
            return self.timeline_stage(data, user)
        elif endpoint == '/home_use_type':
            return self.home_use_type(data, user)
        elif endpoint == '/budget_payment':
            return self.budget_payment(data, user)
        elif endpoint == '/personal_info':
            return self.personal_info(data, user)
        elif endpoint == '/real_estate_agent':
            return self.real_estate_agent(data, user)
        elif endpoint == '/borrower':
            return self.co_borrower(data, user)
        elif endpoint == '/citizenship_financial_history':
            return self.citizenship_financial_history(data, user)
        elif endpoint == '/va_first_time_homebuyer':
            return self.va_first_time_homebuyer(data, user)
        elif endpoint == '/credit_score':
            return self.credit_score(data, user)
        else:
            return jsonify({"status": "error", "message": "Invalid endpoint"}), 404

    def timeline_stage(self, data, user):
        stage = data.get('stage')
        zipcode = data.get('zipcode')
        
        # Validate stage
        if not stage or stage not in [e.value for e in TimelineStage]:
            return jsonify({"status": False, "message": "Invalid stage data"}), 400
        
        # Validate zipcode using Google Maps API
        if zipcode:
            try:
                google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
                geocoder = GoogleV3(api_key=google_location_api_key)
                location = geocoder.geocode(zipcode)
                
                if location:
                    # Check if the geocoded location includes a postal code
                    for component in location.raw.get('address_components', []):
                        if 'postal_code' in component.get('types', []):
                            if component['long_name'] == zipcode:
                                # Save valid stage and zipcode in database
                                current_app.db.pre_qualified.update_one(
                                    {'uuid': user['uuid']},
                                    {'$push': {'timeline_stage': {'stage': stage, 'zipcode': zipcode}}},
                                    upsert=True
                                )
                                return jsonify({"status": True, "message": "Timeline stage and zipcode data received", "stage": stage, "zipcode": zipcode}), 200
                            else:
                                return jsonify({"status": False, "message": "ZIP code does not match location"}), 400
                    
                    return jsonify({"status": False, "message": "ZIP code not found in geocoded data"}), 400
                else:
                    return jsonify({"status": False, "message": "Invalid location"}), 400
                    
            except Exception as e:
                logger.error(f"Error validating zipcode: {str(e)}")
                return jsonify({"status": False, "message": f"Failed to validate zipcode: {str(e)}"}), 500
        else:
            # Save only stage if zipcode is not provided
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'timeline_stage': {'stage': stage}}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Timeline stage data received", "stage": stage}), 200



    def home_use_type(self, data, user):
        home_use = data.get('home_use')
        if home_use and home_use in [e.value for e in HomeUse]: 
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'home_use_type': home_use}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Home use/type data received", "home_use": home_use}), 200
        return jsonify({"status": False, "message": "Invalid optional data"}), 200

    def budget_payment(self, data, user):
        budget = data.get('budget')
        monthly_payment = data.get('monthly_payment')
        down_payment = data.get('down_payment')
        current_app.db.pre_qualified.update_one(
            {'uuid': user['uuid']},
            {'$push': {'budget_payment': {
                'budget': budget, 
                'monthly_payment': monthly_payment, 
                'down_payment': down_payment
            }}},
            upsert=True
        )
        return jsonify({"status": True, "message": "Budget/payment data received", "budget": budget, "monthly_payment": monthly_payment, "down_payment": down_payment}), 200

        


    def personal_info(self, data, user):
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        email = data.get('email')
        phone_number = data.get('phone_number')
        zipcode = data.get('zipcode')  # New field for zipcode

        if not all([first_name, last_name, email, phone_number, zipcode]):
            return jsonify({"status": "error", "message": "All personal information fields are mandatory"}), 400

        try:
            google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
            geocoder = GoogleV3(api_key=google_location_api_key)
            locations = geocoder.geocode(zipcode, exactly_one=False)  # Fetch multiple results

            if not locations:
                return jsonify({
                    "status": "error",
                    "message": "Invalid ZIP code or no addresses found"
                }), 400

            possible_addresses = []
            for location in locations:
                street_number = None
                route = None
                unit = None
                city = None
                state = None
                retrieved_zipcode = None

                # Debug: Print the raw location data
                print(f"Location Raw Data: {location.raw}")

                # Loop through address components
                for component in location.raw.get('address_components', []):
                    if 'street_number' in component.get('types', []):
                        street_number = component['long_name']
                    elif 'route' in component.get('types', []):
                        route = component['long_name']
                    elif 'subpremise' in component.get('types', []):
                        unit = component['long_name']
                    elif 'locality' in component.get('types', []):
                        city = component['long_name']
                    elif 'administrative_area_level_1' in component.get('types', []):
                        state = component['short_name']
                    elif 'postal_code' in component.get('types', []):
                        retrieved_zipcode = component['long_name']

                # Combine street number and route to form the full street address
                if street_number and route:
                    street_address = f"{street_number} {route}"
                else:
                    street_address = location.raw.get('formatted_address', None)

                # Debug: Log the constructed address and ZIP code
                print(f"Constructed Address: {street_address}, ZIP: {retrieved_zipcode}")

                # Add the address to the list regardless of whether the zip code matches exactly
                if street_address:
                    possible_addresses.append({
                        "street_address": street_address,
                        "unit": unit,
                        "city": city,
                        "state": state,
                        "zipcode": retrieved_zipcode  # Using the retrieved zipcode here
                    })

            if possible_addresses:
                return jsonify({
                    "status": "success",
                    "message": "Personal information and address data received",
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "phone_number": phone_number,
                    "possible_addresses": possible_addresses
                }), 200
            else:
                return jsonify({"status": "error", "message": "No valid addresses found for the given ZIP code"}), 400

        except Exception as e:
            logger.error(f"Error validating zipcode: {str(e)}")
            return jsonify({"status": "error", "message": f"Failed to validate zipcode: {str(e)}"}), 500


    def real_estate_agent(self, data, user):
        has_agent = data.get('has_agent')
        if has_agent and has_agent in [e.value for e in EstateAgent]:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'real_estate_agent': has_agent}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Real estate agent data received", "has_agent": has_agent}), 200
        return jsonify({"status": False, "message": "real_estate_agent data optional"}), 400
    
    def co_borrower(self, data, user):
        borrower_status = data.get('borrower_status')
        if borrower_status and borrower_status in [e.value for e in ForHome]: 
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'co_borrower': borrower_status}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Co-borrower data received", "borrower_status": borrower_status}), 200
        return jsonify({"status": False, "message": "borrower data optional"}), 400

    def citizenship_financial_history(self, data, user):
        citizenship_status = data.get('status')
        if citizenship_status and citizenship_status in [e.value for e in EstateAgent]:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'citizenship_financial_history': citizenship_status}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Citizenship/Financial history data received", "history_status": citizenship_status}), 200
        return jsonify({"status": False, "message": "status data optional"}), 400

    def va_first_time_homebuyer(self, data, user):
        about_loan = data.get('loan')
        if about_loan and about_loan in [e.value for e in EstateAgent]:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'va_first_time_homebuyer': about_loan}},
                upsert=True
            )
            return jsonify({"status": True, "message": "VA/First time homebuyer data received", "va_loan_eligibility": about_loan}), 200
        return jsonify({"status": False, "message": "loan_inquiry data optional"}), 200
    
    def credit_score(self, data, user):
        credit_score = data.get('credit_score')
        if credit_score and credit_score in [e.value for e in CreditScore]:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'credit_score': credit_score}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Credit score data received", "credit_score": credit_score}), 200
        return jsonify({"status": False, "message": "Credit score data optional"}), 200
