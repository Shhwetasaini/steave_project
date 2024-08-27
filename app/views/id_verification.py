import os
from datetime import datetime
from app.services.admin import log_request
from app.services.verification import save_file 
from app.services.authentication import custom_jwt_required, log_action
from flask.views import MethodView
from flask_jwt_extended import get_jwt_identity
from flask import request, jsonify, current_app
from email_validator import validate_email, EmailNotValidError


class IDVerificationView(MethodView):
    decorators = [custom_jwt_required()]

    def post(self):
        log_request()
        data = request.form
        passport_front = request.files.get('passportFront', None)
        passport_back = request.files.get('passportBack', None)
        license_front = request.files.get('licenseFront', None)
        license_back = request.files.get('licenseBack', None)
        face_video = request.files.get('faceVideo', None)
        current_user = get_jwt_identity()

        try:
            validate_email(current_user)
            user = current_app.db.users.find_one({'email': current_user})
        except EmailNotValidError:
            user = current_app.db.users.find_one({'uuid': current_user})

        if not user:
            return jsonify({'error': 'User not found'}), 404

        if not (passport_front and passport_back) and not (license_front and license_back):
            return jsonify({"error": "Either passport or license is required."}), 400

        if not face_video:
            return jsonify({'error': "Face video is required."}), 400

        upload_folder = current_app.config['UPLOAD_FOLDER']
        user_docs_dir = os.path.join(upload_folder, 'id_verification', 'verification_docs')
        os.makedirs(user_docs_dir, exist_ok=True)

        verification_document = {}

        if passport_front and passport_back:
            passport_front_path = save_file(passport_front, user_docs_dir)
            passport_back_path = save_file(passport_back, user_docs_dir)
            verification_document['passport'] = {
                'front': passport_front_path,
                'back': passport_back_path
            }

        if license_front and license_back:
            license_front_path = save_file(license_front, user_docs_dir)
            license_back_path = save_file(license_back, user_docs_dir)
            verification_document['license'] = {
                'front': license_front_path,
                'back': license_back_path
            }

        if face_video:
            face_video_path = save_file(face_video, user_docs_dir, file_type='video')
            verification_document['face_video'] = face_video_path

        verification_document['verification_date'] = datetime.now()

        current_app.db.ID_verifications.update_one(
            {'user_id': user['uuid']},
            {
                '$setOnInsert': {
                    'user_id': user['uuid'],
                    'documents': []
                }
            },
            upsert=True
        )

        current_app.db.ID_verifications.update_one(
            {'user_id': user['uuid']},
            {
                '$push': {'documents': verification_document}
            }
        )

        log_action(user['uuid'], user['role'], "ID Verification", verification_document)

        return jsonify({"message": "ID verification documents uploaded successfully."}), 201
