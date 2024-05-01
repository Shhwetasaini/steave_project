
from datetime import datetime
from email_validator import validate_email, EmailNotValidError

from flask.views import MethodView
from flask_jwt_extended import get_jwt_identity
from flask import jsonify, request
from flask import current_app

from app.services.admin import log_request
from app.services.authentication import custom_jwt_required


def store_notification(user_id, title, message, type):
    # Check if the user exists in the notifications collection
    existing_user = current_app.db.notifications.find_one({"user_id": user_id})

    # Construct notification document
    notification = {"title": title, "message": message, "timestamp": datetime.now(), 'type':type}

    if existing_user:
        # User exists, update the notifications array
        current_app.db.notifications.update_one(
            {"user_id": user_id},
            {"$push": {"notifications": notification}}
        )
    else:
        # User does not exist, create a new document
        current_app.db.notifications.insert_one({"user_id": user_id, "notifications": [notification]})   


class NotificationView(MethodView):
    decorators=[custom_jwt_required()]

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

        pipeline = [
            {"$match": {"user_id": user['uuid']}},
            {"$unwind": "$notifications"},
            {"$sort": {"notifications.timestamp": -1}},
            {"$group": {"_id": "$_id", "notifications": {"$push": "$notifications"}}}
        ]

        user_notifications = current_app.db.notifications.aggregate(pipeline)

        notifications = list(user_notifications)
        if notifications:
            return jsonify(notifications[0]['notifications'])
        else:
            return jsonify([])
        