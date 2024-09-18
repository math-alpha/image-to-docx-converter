from flask import Flask, render_template, request, send_file, flash, redirect
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from msrest.authentication import CognitiveServicesCredentials
from msrest.exceptions import HttpOperationError
from docx import Document
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')  # Replace with a secure key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'bmp', 'gif'}

# Configure logging
logging.basicConfig(level=logging.INFO)

# Azure Cognitive Services credentials
AZURE_ENDPOINT = os.getenv('AZURE_ENDPOINT')
AZURE_SUBSCRIPTION_KEY = os.getenv('AZURE_SUBSCRIPTION_KEY')

# Initialize the Computer Vision client
computervision_client = ComputerVisionClient(
    AZURE_ENDPOINT, CognitiveServicesCredentials(AZURE_SUBSCRIPTION_KEY)
)

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Check if a file is uploaded
        if 'file' not in request.files:
            flash('No file part.')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            # Ensure the uploads directory exists
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])

            # Securely save the uploaded file
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            try:
                # Perform OCR using Azure Cognitive Services
                with open(filepath, 'rb') as image_stream:
                    # Submit the image for OCR and get the operation location
                    read_response = computervision_client.read_in_stream(
                        image=image_stream, raw=True
                    )
                    read_operation_location = read_response.headers["Operation-Location"]
                    operation_id = read_operation_location.split("/")[-1]

                # Poll for the result
                while True:
                    read_result = computervision_client.get_read_result(operation_id)
                    if read_result.status.lower() not in ['notstarted', 'running']:
                        break
                    time.sleep(1)

                # Extract text from the OCR results
                extracted_text = ''
                if read_result.status.lower() == 'succeeded':
                    for page in read_result.analyze_result.read_results:
                        for line in page.lines:
                            extracted_text += line.text + '\n'
                else:
                    app.logger.error('Azure OCR failed with status: %s', read_result.status)
                    flash('Could not process the image.')
                    return redirect(request.url)

                # Create a Word document with the extracted text
                document = Document()
                document.add_paragraph(extracted_text)
                docx_filename = filename.rsplit('.', 1)[0] + '.docx'
                docx_path = os.path.join(app.config['UPLOAD_FOLDER'], docx_filename)
                document.save(docx_path)

                # Serve the .docx file to the user
                return send_file(docx_path, as_attachment=True)

            except HttpOperationError as e:
                app.logger.error('Azure Computer Vision HTTP error: %s', e.message, exc_info=True)
                flash('Azure Computer Vision encountered an HTTP error.')
                return redirect(request.url)
            except Exception as e:
                app.logger.error('An unexpected error occurred: %s', str(e), exc_info=True)
                flash('An unexpected error occurred.')
                return redirect(request.url)

            finally:
                # Clean up the uploaded file
                if os.path.exists(filepath):
                    os.remove(filepath)
                # Optionally, clean up the generated DOCX file after sending
                # if os.path.exists(docx_path):
                #     os.remove(docx_path)
        else:
            flash('Allowed file types are png, jpg, jpeg, bmp, gif.')
            return redirect(request.url)
    return render_template('index.html')

if __name__ == '__main__':
    # For testing purposes, run in debug mode
    app.run(debug=True, host='0.0.0.0', port=5000)
    # For production, use Waitress or another WSGI server
    # from waitress import serve
    # serve(app, host='0.0.0.0', port=5000)
