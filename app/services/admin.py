from flask import request, current_app, url_for
import logging
import os
from datetime import datetime

from app.services.media import document_exists, extract_first_page_as_image, resource_exists

logging.basicConfig(level=logging.DEBUG)

def log_request(req: request):
    logging.info(f"Request Method: {req.method}")
    logging.info(f"Request URL: {req.url}")
    logging.info(f"Request Headers: {req.headers}")
    if req.method == 'POST':
        logging.info("Request Form Data: {}".format(req.form if req.form else req.json))


def get_folders_and_files(root_dir):
    def get_files_in_folder(folder_path):
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        return files
    
    folders = [name for name in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, name))]
    folders_and_files = {}
    for folder in folders:
        folder_path = os.path.join(root_dir, folder)
        files = get_files_in_folder(folder_path)
        folders_and_files[folder] = files
    return folders_and_files


# Function to check if file exists in the folder
def file_exists_in_folder(folder_path, filename):
    filepath = os.path.join(folder_path, filename)
    return os.path.isfile(filepath)


def rename_filename(docname, rename, folder):
    root_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', folder)
    files_to_rename = []  # Collect files that need renaming
    
    # Remove .pdf extension from docname
    docname_without_extension = os.path.splitext(docname)[0]

    # Collect files that need renaming
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            # Check if the file starts with the docname without extension
            if file.startswith(docname_without_extension):
                files_to_rename.append((root, file))

    # Rename collected files
    for root, file in files_to_rename:
        # Construct the old and new file paths
        old_path = os.path.join(root, file)
        base, extension = os.path.splitext(file)
        new_path = os.path.join(root, rename + extension)
        os.rename(old_path, new_path)
    
    return new_path


def update_files_in_documents_db():
    flforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'FL_Forms')
    mnforms_docs_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', 'MN_Forms')
    for forms_dir in [flforms_docs_dir, mnforms_docs_dir]:
        forms_type = "FL_Forms" if forms_dir == flforms_docs_dir else "MN_Forms"
        for folder in os.listdir(forms_dir):
            folder_path = os.path.join(forms_dir, folder)
            if os.path.isdir(folder_path):
                for file in os.listdir(folder_path):
                    if file.endswith('.pdf'):
                        doc_name = file
                        doc_url = url_for('serve_media', filename=os.path.join('templates/' + forms_type, folder, file).replace('\\', '/'))
                        preview_page_url = doc_url[:-4] + '.jpg'
                        # Check if document already exists in MongoDB
                        if not document_exists(doc_name):
                            image_name = extract_first_page_as_image(os.path.join(folder_path, file))
                            if image_name:
                                # Check if preview image already exists in MongoDB and folder
                                if not resource_exists(preview_page_url, doc_url):
                                    # Store data in MongoDB
                                    document_data = {
                                        'name': doc_name,
                                        'url': doc_url,
                                        'added_at': datetime.now(),
                                        'preview_image': preview_page_url,
                                        'description': "",
                                        'type': forms_type
                                    }
                                    current_app.db.documents.insert_one(document_data)

