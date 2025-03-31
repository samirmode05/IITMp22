import os
import io
import csv
import zipfile
import tempfile
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Get AI Proxy Token from environment variables
AI_PROXY_TOKEN = os.getenv('AI_PROXY_TOKEN')
AI_PROXY_URL = os.getenv('AI_PROXY_URL', 'https://aiproxy.sanand.workers.dev/')

ALLOWED_EXTENSIONS = {'csv', 'zip', 'txt', 'pdf', 'xlsx', 'json'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_zip_file(file):
    """Extract and process content from a ZIP file"""
    with tempfile.NamedTemporaryFile(delete=False) as temp:
        file.save(temp.name)
        file_contents = {}
        with zipfile.ZipFile(temp.name, 'r') as zip_ref:
            # Prioritize CSV files and look for "answer" column
            for file_info in zip_ref.infolist():
                if file_info.filename.lower().endswith('.csv'):
                    with zip_ref.open(file_info) as f:
                        csv_content = f.read().decode('utf-8', errors='ignore')
                        reader = csv.reader(io.StringIO(csv_content))
                        rows = list(reader)
                        
                        # Check for "answer" column and return first value
                        if rows and 'answer' in rows[0]:
                            answer_idx = rows[0].index('answer')
                            if len(rows) > 1 and len(rows[1]) > answer_idx:
                                file_contents[file_info.filename] = {
                                    'type': 'csv',
                                    'direct_answer': rows[1][answer_idx],
                                    'headers': rows[0],
                                    'data': rows[1:],
                                    'raw': csv_content
                                }
                                continue
                        
                        file_contents[file_info.filename] = {
                            'type': 'csv',
                            'headers': rows[0] if rows else [],
                            'data': rows[1:] if len(rows) > 1 else [],
                            'raw': csv_content
                        }
        os.unlink(temp.name)
        return file_contents

def process_csv_file(file):
    """Process a CSV file and return structured data, ensuring robust handling of edge cases"""
    stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
    file.stream.seek(0)  # Reset file pointer for potential reuse
    rows = list(csv.reader(stream))
    headers = rows[0] if rows else []
    data = rows[1:] if len(rows) > 1 else []
    
    # Check if there's an "answer" column and handle potential missing data
    answer_col_index = -1
    if 'answer' in headers:
        answer_col_index = headers.index('answer')
    
    # If answer column exists and has data, extract the first value
    direct_answer = None
    if answer_col_index >= 0 and data:
        direct_answer = data[0][answer_col_index] if len(data[0]) > answer_col_index else None
    
    return {
        'headers': headers,
        'data': data,
        'answer_col_index': answer_col_index,
        'direct_answer': direct_answer
    }

def extract_data_from_file(file):
    """Extract data from uploaded file based on its type"""
    if not file or not file.filename:
        return None
        
    filename = secure_filename(file.filename)
    file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if file_extension == 'zip':
        return {
            'file_type': 'zip',
            'filename': filename,
            'contents': process_zip_file(file)
        }
    elif file_extension == 'csv':
        return {
            'file_type': 'csv',
            'filename': filename,
            'content': process_csv_file(file)
        }
    else:
        # For other file types, read as text
        content = file.read().decode('utf-8', errors='ignore')
        return {
            'file_type': file_extension,
            'filename': filename,
            'content': content
        }

def get_answer_from_ai(question, file_data=None):
    """Get answer from AI service using the proxy token"""
    
    # First check for direct answers in files
    if file_data:
        # Check ZIP files first
        if file_data.get('file_type') == 'zip':
            for filename, content in file_data.get('contents', {}).items():
                if content.get('direct_answer'):
                    return {"answer": content['direct_answer']}, 200
                
        # Then check single CSV files
        elif file_data.get('file_type') == 'csv':
            direct_answer = file_data.get('content', {}).get('direct_answer')
            if direct_answer:
                return {"answer": direct_answer}, 200

    if not AI_PROXY_TOKEN or not AI_PROXY_URL:
        return {"error": "AI Proxy Token or URL not configured"}, 500

    # Special handling for direct answers in CSV files
    if file_data and file_data.get('file_type') == 'csv' and file_data.get('content', {}).get('direct_answer'):
        return {"answer": file_data['content']['direct_answer']}, 200
        
    # Special handling for CSVs inside ZIP files
    if file_data and file_data.get('file_type') == 'zip':
        for filename, content in file_data.get('contents', {}).items():
            if content.get('type') == 'csv' and 'answer' in content.get('headers', []):
                answer_idx = content['headers'].index('answer')
                if content.get('data') and len(content['data'][0]) > answer_idx:
                    return {"answer": content['data'][0][answer_idx]}, 200

    # Prepare a structured context for the AI, ensuring clarity in the prompt
    context = ""
    if file_data:
        if file_data.get('file_type') == 'zip':
            context += f"File: {file_data.get('filename')}\n"
            context += "Contents:\n"
            for filename, content in file_data.get('contents', {}).items():
                if content.get('type') == 'csv':
                    context += f"- {filename} (CSV file)\n"
                    context += f"  Headers: {', '.join(content.get('headers', []))}\n"
                    context += f"  Data sample: {content.get('data', [])[:3]}\n"
                else:
                    context += f"- {filename} (Content sample: {content.get('content', '')[:100]}...)\n"
        elif file_data.get('file_type') == 'csv':
            context += f"File: {file_data.get('filename')} (CSV)\n"
            context += f"Headers: {file_data.get('content', {}).get('headers', [])}\n"
            context += f"Data sample: {file_data.get('content', {}).get('data', [])[:3]}\n"
        else:
            context += f"File: {file_data.get('filename')} (Content sample: {file_data.get('content', '')[:100]}...)\n"

    # Prepare the prompt
    prompt = f"""
    You are a helper for IIT Madras Online Degree in Data Science course. 
    
    Task: Provide the answer to the following question from a graded assignment:
    
    Question: {question}
    
    {context}
    
    Important: Your response must be ONLY the answer value, without any explanation or additional text.
    The answer should be the exact value that would be entered in the assignment form.
    """

    # Make API request to AI service
    headers = {
        "Authorization": f"Bearer {AI_PROXY_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4",  # Using GPT-4 for higher accuracy
        "messages": [
            {"role": "system", "content": "You are a helpful assistant for IIT Madras Data Science students."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1  # Low temperature for more deterministic output
    }
    
    try:
        response = requests.post(AI_PROXY_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        # Extract the answer from the response
        answer = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        # Clean up the answer - remove any markdown formatting or extra text
        answer = answer.strip()
        answer = answer.strip('`')  # Remove code block formatting
        
        # If the answer contains multiple lines, take only the first line
        if '\n' in answer:
            answer = answer.split('\n')[0].strip()
            
        return {"answer": answer}, 200
    
    except requests.exceptions.RequestException as e:
        return {"error": f"AI service error: {str(e)}"}, 500
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}, 500

@app.route('/api/', methods=['POST'])
def solve_question():
    """Main endpoint to handle question solving requests"""
    try:
        # Validate content type
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            return jsonify({"error": "Content-Type must be multipart/form-data"}), 415
            
        # Check if the question is provided
        if 'question' not in request.form:
            return jsonify({"error": "Question parameter is required"}), 400
        
        question = request.form['question'].strip()
        if not question:
            return jsonify({"error": "Question cannot be empty"}), 400
        
        # Process file if provided
        file_data = None
        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            if not allowed_file(file.filename):
                return jsonify({"error": f"File type not allowed. Supported types: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
            try:
                file_data = extract_data_from_file(file)
            except Exception as e:
                app.logger.error(f"File processing error: {str(e)}")
                return jsonify({"error": "Failed to process uploaded file"}), 400
        
        # Get answer from AI service
        response, status_code = get_answer_from_ai(question, file_data)
        
        # Ensure response format is correct
        if status_code == 200 and "answer" in response:
            return jsonify({"answer": str(response["answer"])}), 200
        else:
            return jsonify(response), status_code
            
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/', methods=['GET'])
def home():
    """Home route to confirm the API is running"""
    return jsonify({
        "status": "online",
        "message": "TDS Solver API is running. Use POST /api/ to submit questions."
    })

def ensure_test_files():
    """Create test files if they don't exist"""
    test_files_dir = os.path.join(os.path.dirname(__file__), 'test_files')
    os.makedirs(test_files_dir, exist_ok=True)

    # Create test ZIP file containing the extract.csv
    csv_path = os.path.join(test_files_dir, 'extract.csv')
    zip_path = os.path.join(test_files_dir, 'sample.zip')
    
    if os.path.exists(csv_path):
        try:
            # Create new ZIP file with the CSV
            with zipfile.ZipFile(zip_path, 'w') as zf:
                # Add CSV to ZIP with a relative path
                zf.write(csv_path, 'extract.csv')
            app.logger.info(f"Created test ZIP file at {zip_path}")
            return zip_path
        except Exception as e:
            app.logger.error(f"Failed to create ZIP file: {str(e)}")
            return None
    return None

@app.route('/test', methods=['GET'])
def test():
    """Test endpoint with sample data"""
    try:
        app.logger.info("Starting test endpoint...")
        zip_path = ensure_test_files()
        
        if not zip_path or not os.path.exists(zip_path):
            return jsonify({
                "status": "error",
                "message": "Could not find or create test files"
            }), 404

        app.logger.info(f"Using ZIP file: {zip_path}")
        
        with open(zip_path, 'rb') as f:
            try:
                # Prepare multipart form data
                files = {'file': ('sample.zip', f, 'application/zip')}
                data = {'question': 'What is the value in the "answer" column of the CSV file?'}
                
                # Make request to local API
                response = requests.post(
                    f"{request.url_root.rstrip('/')}/api/",
                    files=files,
                    data=data
                )
                
                app.logger.info(f"API Response: {response.status_code} - {response.text}")
                
                if response.ok:
                    return jsonify(response.json()), response.status_code
                else:
                    return jsonify({
                        "status": "error",
                        "message": "API request failed",
                        "details": response.text
                    }), response.status_code
                    
            except Exception as e:
                app.logger.error(f"Test request failed: {str(e)}")
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500

    except Exception as e:
        app.logger.error(f"Test endpoint error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
