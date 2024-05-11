import os
import hashlib
from datetime import datetime 
import json

from flask.views import MethodView
from flask import jsonify, request, url_for
from flask import current_app
from werkzeug.utils import secure_filename
from flask_jwt_extended import get_jwt_identity

from app.services.authentication import custom_jwt_required
from app.services.admin import (
    log_request, 
    get_folders_and_files, 
    file_exists_in_folder, 
    rename_filename,
    update_files_in_documents_db
)


class AllDocumentsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        
        documents = list(current_app.db.documents.find({},{'_id':False}))
        log_action(user['uuid'],user['role'],user['email'],"get-all-documents",None)
        return jsonify(documents), 200
         

class EditDocumentsView(MethodView):
    decorators =  [custom_jwt_required()]
    def put(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
      
        update_doc = {}
        
        data = request.json
        docname = data.get('docname')
        description =  data.get('description')
        rename = data.get('rename')
        folder = data.get('folder')
        
        if description:
            update_doc['description'] = description
        if rename:
            document = current_app.db.documents.find_one({'name' : rename + '.pdf'})
            if not document:
                new_url = rename_filename(docname, rename, folder)
                updated_path = os.path.splitext(new_url)[0]
                pdf_path = updated_path + '.pdf'
                updated_pdf_path = pdf_path.rsplit('templates/')
                doc_url = url_for('serve_media', filename=os.path.join('templates/'+ updated_pdf_path[1]).replace('\\', '/'))
                preview_page_url = doc_url[:-4] + '.jpg'
                update_doc['name'] = rename + '.pdf'
                update_doc['url'] = doc_url
                update_doc['preview_image'] = preview_page_url
            else:
                return jsonify({'error': 'File with this name already exist!'}), 400 
            
        update_doc['updated_at'] = datetime.now()
        updated_document = current_app.db.documents.find_one_and_update(
            {"name": docname},
            {"$set": update_doc},
            return_document=True 
        )
        log_action(user['uuid'],user['role'],user['email'],"updated-document",update_doc)
        if updated_document:
            return jsonify({'message': 'Document Updated Successfully!'})       



class FlFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        
        root_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms')
        folders_and_files = get_folders_and_files(root_dir)
        log_action(user['uuid'],user['role'],user['email'],"viewed-FL-forms",None)
        return jsonify(folders_and_files), 200
       


class MnFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        root_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms')
        folders_and_files = get_folders_and_files(root_dir)
        log_action(user['uuid'],user['role'],user['email'],"viewed-ML-forms",None)
        return jsonify(folders_and_files), 200
       


class SingleFlFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, filename, folder):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        # Specify the folder path
        folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', folder)
        # Check if the file exists in the folder
        if file_exists_in_folder(folder_path, filename):
            # Query MongoDB collection for the document object
            document = current_app.db.documents.find_one({'name': filename},  {'_id': 0})
            if document:
                log_action(user['uuid'],user['role'],user['email'],"viewed-single-FL-forms",None)
                return jsonify(document), 200
            else:
                return jsonify({'error': 'Document not found in the database'}), 404
        else:
            return jsonify({'error': 'File not found in the folder'}), 404


class SingleMnFormsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, filename, folder):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        # Specify the folder path
        folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', folder)

        # Check if the file exists in the folder
        if file_exists_in_folder(folder_path, filename):
            # Query MongoDB collection for the document object
            document = current_app.db.documents.find_one({'name': filename},  {'_id': 0})
            if document:
                log_action(user['uuid'],user['role'],user['email'],"viewed-single-ML-forms",None)
                return jsonify(document), 200
            else:
                return jsonify({'error': 'Document not found in the database'}), 404
        else:
            return jsonify({'error': 'File not found in the folder'}), 404


class UploadDocumentView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        update_doc = {}

        data = request.form
        folder_type = data.get('folder_type')
        folder = data.get('folder') 
        new_folder = data.get('new_folder')
        file = request.files.get('file')
        if folder:
            file_folder = folder
        else:
            file_folder = new_folder
        filename = file.filename
        document  = current_app.db.documents.find_one({'name': filename})
        if document:
            return jsonify({'error': 'File with this name already exist!'}), 400 
        file_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', folder_type, file_folder)
        os.makedirs(file_dir, exist_ok=True)
        file_path = os.path.join(file_dir, filename)
        file.save(file_path)
        document_data = update_files_in_documents_db()
        data['document_data']=document_data
        log_action(user['uuid'],user['role'],user['email'],"uploaded-document",data)
        return jsonify({'message': 'File uploaded succesfully'}), 200
        


class MoveFlFormsFileView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        try:
            
            # Get data from the frontend
            filename_with_extension = request.json.get('filename')
            source_folder = request.json.get('source_folder')
            dest_folder = request.json.get('dest_folder')

            # Extract filename and extension
            filename, extension = os.path.splitext(filename_with_extension)

            # Determine source and destination paths for both file extensions
            source_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', source_folder, filename_with_extension)
            source_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', source_folder, filename + '.jpg')
            dest_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder, filename_with_extension)
            dest_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder, filename + '.jpg')

            # Create destination folder if it doesn't exist
            dest_folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms', dest_folder)
            os.makedirs(dest_folder_path, exist_ok=True)

            # Move both files
            os.rename(source_pdf_path, dest_pdf_path)
            os.rename(source_jpg_path, dest_jpg_path)

             # Update MongoDB documents with the new URLs
            doc_name = filename_with_extension
            doc_url = url_for('serve_media', filename=os.path.join('templates', 'FL_Forms', dest_folder, filename_with_extension))
            preview_page_url = url_for('serve_media', filename=os.path.join('templates', 'FL_Forms', dest_folder, filename + '.jpg'))
            
            # Find the existing document in MongoDB
            existing_document = current_app.db.documents.find_one({'name': doc_name})
            
            # Update the existing document if found
            if not existing_document:
                return jsonify({'error': 'File does not exist!'}), 404

            current_app.db.documents.update_one(
                {'name': doc_name},
                {'$set': {
                    'url': doc_url,
                    'added_at': datetime.now(),
                    'preview_image': preview_page_url,
                    'type': 'FL_Forms'
                }}
            )
            data = {'source_folder':source_folder,
                    'dest_folder':dest_folder,
                    'file':doc_url,
                    'preview_image':preview_page_url}

            log_action(user['uuid'],user['role'],user['email'],"move-FL-forms",data)
            return jsonify({'message': 'Files moved successfully'}), 200
        except Exception as e:
            print(str(e))
            return jsonify({'error': str(e)}), 500


class MoveMnFormsFileView(MethodView):
    decorators =  [custom_jwt_required()]
    def post(self):
        log_request(request)
        current_user = get_jwt_identity()
        user = current_db.users.find_one({'email': current_user})
        try:
            # Get data from the frontend
            filename_with_extension = request.json.get('filename')
            source_folder = request.json.get('source_folder')
            dest_folder = request.json.get('dest_folder')

            # Extract filename and extension
            filename, extension = os.path.splitext(filename_with_extension)

            # Determine source and destination paths for both file extensions
            source_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', source_folder, filename_with_extension)
            source_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', source_folder, filename + '.jpg')
            dest_pdf_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder, filename_with_extension)
            dest_jpg_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder, filename + '.jpg')

            # Create destination folder if it doesn't exist
            dest_folder_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms', dest_folder)
            os.makedirs(dest_folder_path, exist_ok=True)

            # Move both files
            os.rename(source_pdf_path, dest_pdf_path)
            os.rename(source_jpg_path, dest_jpg_path)

             # Update MongoDB documents with the new URLs
            doc_name = filename_with_extension
            doc_url = url_for('serve_media', filename=os.path.join('templates', 'MN_Forms', dest_folder, filename_with_extension))
            preview_page_url = url_for('serve_media', filename=os.path.join('templates', 'MN_Forms', dest_folder, filename + '.jpg'))
            
            # Find the existing document in MongoDB
            existing_document = current_app.db.documents.find_one({'name': doc_name})
            
            # Update the existing document if found
            if not existing_document:
                return jsonify({'error': 'File does not exist!'}), 404

            current_app.db.documents.update_one(
                {'name': doc_name},
                {'$set': {
                    'url': doc_url,
                    'added_at': datetime.now(),
                    'preview_image': preview_page_url,
                    'type': 'FL_Forms'
                }}
            )
            data = {'source_folder':source_folder,
                    'dest_folder':dest_folder,
                    'file':doc_url,
                    'preview_image':preview_page_url}

            log_action(user['uuid'],user['role'],user['email'],"move-ML-forms",data)
            return jsonify({'message': 'Files moved successfully'}), 200
        except Exception as e:
            print(str(e))
            return jsonify({'error': str(e)}), 500


class DownloadedDocsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, uuid):
        log_request(request)
        current_user = get_jwt_identity()
        logged_in_user = current_db.users.find_one({'email': current_user})
       
        user = current_app.db.users.find_one({'uuid': uuid}, {'_id': 0})
        if user:
            log_action(logged_in_user['uuid'],logged_in_user['role'],logged_in_user['email'],"move-ML-forms",None)
            return jsonify(user), 200
        else:
            return jsonify({"error":"User does not exist!"}), 404



class UploadedDocsView(MethodView):
    decorators =  [custom_jwt_required()]
    def get(self, uuid):
        log_request(request)
        current_user = get_jwt_identity()
        logged_in_user = current_db.users.find_one({'email': current_user})
        user = current_app.db.users.find_one({'uuid': uuid}, {'_id': 0})
        if user:
            log_action(logged_in_user['uuid'],logged_in_user['role'],logged_in_user['email'],"move-ML-forms",None)
            return jsonify(user), 200
        else:
            return jsonify({"error":"User does not exist!"}), 404
        
