import os
import io
import shutil
import base64
import os
from datetime import datetime

from PyPDF2 import PdfReader, PdfWriter

from flask import current_app, url_for
from pdf2image import convert_from_path 
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment, FileContent, FileName, FileType, Disposition


def extract_first_page_as_image(pdf_file_path):
    images = convert_from_path(pdf_file_path)
    if images:
        image_name = os.path.splitext(os.path.basename(pdf_file_path))[0]
        image_path = os.path.join(os.path.dirname(pdf_file_path), image_name + '.jpg')
        images[0].save(image_path, 'JPEG')
        return image_name + '.jpg'
    else:
        return None


# Function to check if document exists in MongoDB
def document_exists(name):
    return current_app.db.documents.find_one({'name': name}) is not None

  
# Function to check if preview image or URL exists in MongoDB and folder
def resource_exists(preview_page_url, doc_url):
    return (current_app.db.documents.find_one({'$or': [{'preview_image': preview_page_url}, {'url': doc_url}]}) is not None) and \
           (os.path.isfile(preview_page_url) or os.path.isfile(doc_url))


def create_user_document(original_file_path, new_doc_path, user_media_dir, filename, user):
    try:
        # Create the directory if it doesn't exist
        os.makedirs(user_media_dir, exist_ok=True)

        # Copy the original file to the new location
        shutil.copyfile(original_file_path, new_doc_path)

        # Construct the URL for accessing the saved PDF
        doc_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))

        return {'doc_url': doc_url}
    except Exception as e:
        return {"error": str(e)}


# Function to check if the answer is a datetime string
def is_datetime_string(s):
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def check_answer_type(answer):
    if type(answer) == int or type(answer) == float:
        answer_type = 'number'
    elif type(answer) == str:
        if is_datetime_string(answer):
            answer_type = 'datetime'
        else:
            answer_type = 'text'
    elif type(answer) == bool:
        answer_type = 'boolean'
    
    return answer_type


def insert_answer_in_pdf(doc_path, answer_locations, answer, user, values, filename):
    try:
        reader = PdfReader(doc_path)
        writer = PdfWriter()
        # Iterate over each page of the original PDF
        for page_num in range(len(reader.pages)):
            # Get the page object
            page = reader.pages[page_num]

            # Check if there are answer locations for this page
            page_answer_locations = [loc for loc in answer_locations if loc.get('pageNum') == page_num + 1]
            if page_answer_locations:
                # Create a new PDF with ReportLab
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                can.setFillColorRGB(0, 0, 1)
                # Add all answer locations to the overlay
                for location in page_answer_locations:
                    answer_type = check_answer_type(answer)
                    if location['answerInputType'] == 'single-checkbox':
                        if answer_type != location['answerOutputType']:
                            return {'error': 'Answer data type is incorrect for this question'}
                        x = location['startX']
                        y = letter[1] - location['endY'] + 6
                        can.drawString(x, y, '✔')
                    elif location['answerInputType'] == 'multiple-checkbox':
                        if answer_type != location['answerOutputType'] or (not isinstance(values, list) or not values):
                            return {'error': 'Answer data type is correct for this answer or missing value or incorrect datatype for value'}
                        position = location['position']
                        # Filter locations with the same position
                        positions = [loc for loc in page_answer_locations if loc['position'] == position]
                        existing_values = [position.get('value') for position in positions]
                        if len(values) == 1:
                            if values[0] not in existing_values:
                                return {'error': 'incorrect value provided for option to mark'}
                            for pos in positions:
                                if location['value'] == values[0]:
                                    x = location['startX']
                                    y = letter[1] - location['endY'] + 6
                                    can.drawString(x, y, '✔')
                        else:
                            for value in values:
                                if value not in existing_values:
                                    return {'error': 'incorrect value provided for option to mark'}
                                if location['value'] == value:
                                    x = location['startX']
                                    y = letter[1] - location['endY'] + 6
                                    can.drawString(x, y, '✔')
                    elif location['answerInputType'] == 'multiline':
                        if answer_type != location['answerOutputType']:
                            return {'error': 'Answer data type is incorrect for this question'}
                        position = location['position']
                        text = str(answer)
                        # Filter locations with the same position
                        positions = [loc for loc in page_answer_locations if loc['position'] == position]

                        # Track whether there's more text to draw
                        text_index = 0

                        # Iterate over each line position
                        for pos in positions:
                            if text_index >= len(text):
                                break

                            # Set the starting coordinates for the current line
                            x = pos['startX']
                            y = letter[1] - pos['endY'] + 2
                            max_width = pos['endX'] - pos['startX']

                            # Loop to insert text within the line width
                            while text_index < len(text):
                                # Determine the maximum number of characters that fit within the max_width
                                for i in range(len(text) - text_index, 0, -1):
                                    substring_width = can.stringWidth(text[text_index:text_index + i], "Helvetica", 12)
                                    if substring_width <= max_width:
                                        # Draw the substring at the current position
                                        can.drawString(x, y, text[text_index:text_index + i])
                                        # Move the text index forward by the number of characters drawn
                                        text_index += i
                                        break
                                else:
                                    # If no fitting substring is found, break the loop
                                    break
                                
                                # Move to the next line if there's more text to draw
                                if text_index < len(text):
                                    next_pos_index = positions.index(pos) + 1
                                    if next_pos_index < len(positions):
                                        next_pos = positions[next_pos_index]
                                        x = next_pos['startX']
                                        y = letter[1] - next_pos['endY'] + 2
                                        max_width = next_pos['endX'] - next_pos['startX']
                                        break
                                    else:
                                        text_index = len(text)
                                        break
                    else:
                        if answer_type != location['answerOutputType']:
                            return {'error': 'Answer data type is incorrect for this question'}
                        x = location['startX']
                        y = letter[1] - location['endY'] + 2
                        max_width = location['endX'] - location['startX']
                        text = str(answer)
                        for i in range(len(text), -1, -1):
                            if can.stringWidth(text[:i], "Helvetica", 12) <= max_width:
                                can.drawString(x, y, text[:i])
                                break   
                can.save()

                # Move to the beginning of the StringIO buffer
                packet.seek(0)
                new_pdf = PdfReader(packet)

                # Merge the newly created overlay with the existing page
                page.merge_page(new_pdf.pages[0])

            # Add the (possibly modified) original page to the PDF writer
            writer.add_page(page)

        # Write the modified PDF content to a file in the media folder
        with open(doc_path, 'wb') as fp:
            writer.write(fp)

        # Construct the URL for accessing the saved PDF
        doc_url = url_for('serve_media', filename=os.path.join('user_docs', str(user['uuid']), 'uploaded_docs', filename))

        return {'doc_url': doc_url}
    except Exception as e:
        return {"server-error": str(e)}


def send_finalized_document(user, file_path):
    try:
        # Read the PDF file
        with open(file_path, 'rb') as f:
            file_data = f.read()

        # Encode the PDF file in Base64
        encoded_pdf = base64.b64encode(file_data).decode('utf-8')

        # Create the attachment
        attachment = Attachment()
        attachment.file_content = FileContent(encoded_pdf)
        attachment.file_type = FileType('application/pdf')
        attachment.file_name = FileName(os.path.basename(file_path))
        attachment.disposition = Disposition('attachment')

        # Create email content
        subject = "Filled and Signed Document"
        content = Content("text/plain", f"Dear {user.get('first_name')} {user.get('last_name')},\n\nYour document has been finalized.\n\nBest regards,\nAiREBrokers")
        from_email = Email(current_app.config['MAIL_USERNAME'])
        to_email = To(user.get('email'))

        # Create the Mail object
        mail = Mail(from_email, to_email, subject, content)
        mail.attachment = attachment

        # Send the email
        sendgrid_client = SendGridAPIClient(current_app.config['SENDGRID_API_KEY'])
        response = sendgrid_client.send(mail)

        # Check for a successful response
        if response.status_code >= 200 and response.status_code < 300:
            return {'message': 'Email sent successfully'}
        else:
            return {'error': f'Failed to send email: {response.body}'}

    except Exception as e:
        return {'error': str(e)}