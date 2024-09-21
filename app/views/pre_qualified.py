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
from datetime import datetime

logger = logging.getLogger(__name__)

class HomeBuyingStage(Enum):
    FIRST_TIME_BUYER_YES = "Yes"
    FIRST_TIME_BUYER_NO = "No"

class homebuying(Enum):
    THINKING = "I'm thinking about buying"
    LOOKING = "Touring open houses"
    FOUND_HOME = "Making offers on a property"
    REFINANCING = "I've signed a purchase contract"

class TimelineStage(Enum):
    TILLTHREEMONTHS = "0-3 months"
    TILLFOURMONTHS = "4-6 months"
    SEVENPLUSMONTHS = "7+ months"
    NOTSURE = "Not sure"


class HomeUse(Enum):
    PRIMARY = "Primary Residence"
    SECONDARY = "Secondary Residence"
    INVESTMENT = "Investment Property"


class HomeType(Enum):
    SINGLE_FAMILY = "Single Family"
    TOWN_HOUSE = "Town House"
    CONDOMINIUM = "Condominium"
    MOBILE = "Mobile or Manufactured"


class EstateAgent(Enum):
    YES = "Yes"
    NO = "No"

class ForHome(Enum):
    BORROWER = "Alone"
    COBORROWER = "With a co-borrower"

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
        
        if endpoint == '/timeline_homebuying_stage':
            return self.timeline_stage(data, user)
        elif endpoint == '/home_use_type':
            return self.home_use_type(data, user)
        elif endpoint == '/income_employment_details':
            return self.income_employment_detail(data, user)
        elif endpoint == '/personal_info':
            return self.personal_info(data, user)
        elif endpoint == '/budget_details':
            return self.budget_detail(data, user)
        elif endpoint == '/budget_detail':
            return self.budget(data, user)
        elif endpoint == '/credit_score_estimate':
            return self.credit_score(data, user)
        else:
            return jsonify({"status": "error", "message": "Invalid endpoint"}), 404


    def timeline_stage(self, data, user):

        is_first_time = data.get('is_first_time_buyer')  
        stage = data.get('homebuying')  
        timeline = data.get('timeline')  
        zipcode = data.get('zipcode') 

        if not is_first_time or is_first_time not in [e.value for e in HomeBuyingStage]:
            return jsonify({"status": False, "message": "Missing or invalid first-time buyer selection"}), 400

        if not stage or stage not in [e.value for e in homebuying]:
            return jsonify({"status": False, "message": "Missing or invalid home-buying stage data"}), 400

        if not timeline or timeline not in [e.value for e in TimelineStage]:
            return jsonify({"status": False, "message": "Missing or invalid timeline data"}), 400

        if zipcode:
            try:
                google_location_api_key = current_app.config['GOOGLE_LOCATION_API_KEY']
                geocoder = GoogleV3(api_key=google_location_api_key)
                location = geocoder.geocode(zipcode)

                if location:
                    for component in location.raw.get('address_components', []):
                        if 'postal_code' in component.get('types', []):
                            if component['long_name'] == zipcode:
                                current_app.db.pre_qualified.update_one(
                                    {'uuid': user['uuid']},
                                    {'$push': {'timeline_stage': {'is_first_time_buyer': is_first_time, 'stage': stage, 'timeline': timeline, 'zipcode': zipcode}}},
                                    upsert=True
                                )
                                return jsonify({"status": True, "message": "Data received","data": { "is_first_time_buyer": is_first_time, "home_buying_stage": stage, "timeline": timeline, "zipcode": zipcode}}), 200
                            else:
                                return jsonify({"status": False, "message": "ZIP code does not match location"}), 400
                    return jsonify({"status": False, "message": "ZIP code not found in geocoded data"}), 400
                else:
                    return jsonify({"status": False, "message": "Invalid location"}), 400

            except Exception as e:
                logger.error(f"Error validating ZIP code: {str(e)}")
                return jsonify({"status": False, "message": f"Failed to validate ZIP code: {str(e)}"}), 500
        else:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'timeline_stage': {'is_first_time_buyer': is_first_time, 'home_buying_stage': stage, 'timeline': timeline}}},
                upsert=True
            )
            return jsonify({"status": True, "message": "Data received", "data":{"is_first_time_buyer": is_first_time, "home_buying_stage": stage, "timeline": timeline}}), 200

    def home_use_type(self, data, user):
        home_use = data.get('home_use') 
        home_type = data.get('home_type')  

        if home_use and home_use in [e.value for e in HomeUse]:
            if home_type and home_type in [e.value for e in HomeType]:
                current_app.db.pre_qualified.update_one(
                    {'uuid': user['uuid']},
                    {'$push': {'home_use_type': {'home_use': home_use, 'home_type': home_type}}},
                    upsert=True
                )
                return jsonify({
                    "status": True,
                    "message": "Home use/type data received",
                    "data": {
                        "home_use": home_use,
                        "home_type": home_type
                    }
                }), 200
            else:
                return jsonify({"status": False, "message": "Invalid home type data"}), 400
        else:
            return jsonify({"status": False, "message": "Invalid home use data"}), 400

    def income_employment_detail(self, data, user):
        length_of_employment = data.get('length_of_employment')  
        employment_info= data.get('employment_info') 
        employment_title = data.get('employment_title')
        employment_status = data.get('employment_status')
        salary_of_hourly_wage = data.get('salary_of_hourly_wage')
        gross_income = data.get('gross_income')
        net_income = data.get('net_income')
        annual_income = data.get('annual_income')
        current_debets = data.get('current_debets')
        monthly_expenses = data.get('monthly_expenses')

        us_citizen = data.get('are_you_us_citizen')
        foreclosure_history = data.get('foreclosure_history')
        bankruptcy_history = data.get('bankruptcy_history')

        
        if us_citizen not in [e.value for e in EstateAgent]:
            return jsonify({"status": False, "message": "Invalid selection for U.S. citizenship"}), 400

        if foreclosure_history not in [e.value for e in EstateAgent]:
            return jsonify({"status": False, "message": "Invalid selection for foreclosure history"}), 400

        if bankruptcy_history not in [e.value for e in EstateAgent]:
            return jsonify({"status": False, "message": "Invalid selection for bankruptcy history"}), 400

        try:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {
                    'employment_income_details': {
                        'length_of_employment': length_of_employment,
                        'employment_info': employment_info,
                        'employment_title':employment_title,
                        'employment_status':employment_status,
                        'are_you_us_citizen': us_citizen,
                        'foreclosure_history': foreclosure_history,
                        'bankruptcy_history': bankruptcy_history,
                        'salary_of_hourly_wage':salary_of_hourly_wage,
                        'gross_income' :gross_income,
                        'net_income' :net_income,
                        'annual_income' :annual_income,
                        'current_debets' :current_debets,
                        'monthly_expenses':monthly_expenses
                    }
                }},
                upsert=True
            )

            return jsonify({
                "status": True,
                "message": "Employment and Income details saved",
                "data": {
                    'employment_income_details': {
                        'length_of_employment': length_of_employment,
                        'employment_info': employment_info,
                        'employment_title':employment_title,
                        'employment_status':employment_status,
                        'are_you_us_citizen': us_citizen,
                        'foreclosure_history': foreclosure_history,
                        'bankruptcy_history': bankruptcy_history,
                        'salary_of_hourly_wage':salary_of_hourly_wage,
                        'gross_income' :gross_income,
                        'net_income' :net_income,
                        'annual_income' :annual_income,
                        'current_debets' :current_debets,
                        'monthly_expenses':monthly_expenses
                    }
                }
            }), 200

        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")
            return jsonify({"status": False, "message": f"Error saving data: {str(e)}"}), 500                  

    def personal_info(self, data, user):
        first_name = data.get('first_name')
        last_name = data.get('last_name', None)
        email = data.get('email')
        phone_number = data.get('phone_number')
        address = data.get('address')  
        unit = data.get('unit_number', None)

        if not all([first_name, email, phone_number, address]):
            return jsonify({"status": "error", "message": "All personal information fields are mandatory"}), 400

        full_address = f"{address}, Unit: {unit}" if unit else address

        personal_info_data = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone_number": phone_number,
            "full_address": full_address,
            "unit_number": unit,
            "date": datetime.utcnow().strftime('%Y-%m-%d')  
        }

        try:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'personal_info': personal_info_data}},  
                upsert=True  
            )

            return jsonify({
                "status": "success",
                "message": "Personal information received and saved",
                "personal_info": personal_info_data
            }), 200

        except Exception as e:
            logger.error(f"Error saving personal information: {str(e)}")
            return jsonify({"status": "error", "message": f"Error saving data: {str(e)}"}), 500

    def budget_detail(self, data, user):
           
        budget = int(data.get('budget')) if data.get('budget') else None 
        monthly_payment = int(data.get('monthly_payment')) if data.get('monthly_payment') else None  
        down_payment = int(data.get('down_payment')) if data.get('down_payment') else None  
        if not budget or not 1000 <= budget :
            return jsonify({"status": False, "message": "Budget must be <1,000 "}), 400

        if not monthly_payment or not 1000 <= monthly_payment:
            return jsonify({"status": False, "message": "Monthly payment must be <1,000 "}), 400

        if not down_payment or not 1000 <= down_payment:
            return jsonify({"status": False, "message": "Down payment must be <1,000"}), 400

        try:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {
                    'budget_details': {
                        'budget': budget,
                        'monthly_payment': monthly_payment,
                        'down_payment': down_payment
                    }
                }},
                upsert=True
            )

            return jsonify({
                "status": True,
                "message": "Budget details received",
                "data": {
                    "budget": budget,
                    "monthly_payment": monthly_payment,
                    "down_payment": down_payment
                }
            }), 200

        except Exception as e:
            logger.error(f"Error saving budget details: {str(e)}")
            return jsonify({"status": False, "message": f"Error saving budget details: {str(e)}"}), 500
        
    def budget(self, data, user):
        credit_score = data.get('credit_score')  
        is_service_member = data.get('is_service_member') 
        is_real_estate = data.get('is_real_estate')  

        update_data = {}

        if credit_score and credit_score in [e.value for e in ForHome]:  
            update_data['credit_score'] = credit_score
        else:
            return jsonify({"status": False, "message": "Invalid credit score"}), 400

        if is_service_member and is_service_member in ['Yes', 'No']: 
            update_data['is_service_member'] = is_service_member
        else:
            return jsonify({"status": False, "message": "Invalid service member status"}), 400

        if is_real_estate and is_real_estate in ['Yes', 'No']:
            update_data['is_real_estate'] = is_real_estate
        else:
            return jsonify({"status": False, "message": "Invalid real estate agent status"}), 400

        try:
            current_app.db.pre_qualified.update_one(
                {'uuid': user['uuid']},
                {'$push': {'budget_detail': update_data}},  
                upsert=True
            )

            return jsonify({
                "status": True,
                "message": "Credit_score, service member, and real estate data received",
                "data": update_data
            }), 200

        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")
            return jsonify({"status": False, "message": f"Error saving data: {str(e)}"}), 500

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
        