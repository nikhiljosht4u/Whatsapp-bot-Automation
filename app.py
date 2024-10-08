from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
from datetime import datetime
import time

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)

ACCOUNT_SID = '*****************'
AUTH_TOKEN = '*****************'
WHATSAPP_NUMBER = 'whatsapp:*****************'

# Google Sheets credentials and setup
SERVICE_ACCOUNT_FILE = '*****************.json'  # Replace with the path to your service account JSON file
SPREADSHEET_ID = '*****************'  # Replace with your Google Sheet ID

# OAuth2.0 flow setup using service account
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
client_sheets = gspread.authorize(credentials)
try:
    sheet = client_sheets.open_by_key(SPREADSHEET_ID)
except gspread.SpreadsheetNotFound:
    logging.error(f"The spreadsheet with ID {SPREADSHEET_ID} was not found.")
    raise

# Initialize Twilio client
client_twilio = Client(ACCOUNT_SID, AUTH_TOKEN)

# Keep track of current question index for each phone number
current_question_index = {}

# Keep track of whether the initial greeting has been sent for each phone number
initial_greeting_sent = {}

# Mapping of phone numbers to center names
phone_to_center = {
    '123456789': 'LONDON',
    '8951865655': 'PALAKKAD',
    '1234567890': 'NEWYORK',
    '9578765429': 'AFRICA',
    # Add other mappings as needed
}

def fetch_data(worksheet_name):
    try:
        logging.info(f"Fetching data from worksheet: {worksheet_name}")
        worksheet = sheet.worksheet(worksheet_name)
        values = worksheet.get_all_values()
        logging.info(f"Fetched data from {worksheet_name}: {values}")
        return values
    except gspread.WorksheetNotFound:
        logging.error(f"Worksheet named '{worksheet_name}' was not found.")
        return []
    except Exception as e:
        logging.error(f"Error fetching data from worksheet {worksheet_name}: {e}")
        return []

def send_whatsapp_message(message_body, to_number):
    whatsapp_to_number = f"whatsapp:+COUNTRYCODE{to_number}"
    try:
        message = client_twilio.messages.create(
            body=message_body,
            from_=WHATSAPP_NUMBER,
            to=whatsapp_to_number
        )
        logging.info(f"Message sent to {whatsapp_to_number}: {message.sid}")
    except Exception as e:
        logging.error(f"Error sending message to {whatsapp_to_number}: {e}")

def save_response(worksheet_name, response_data):
    try:
        worksheet = sheet.worksheet(worksheet_name)
        worksheet.append_row(response_data)
        logging.info(f"Response saved to {worksheet_name}")
    except Exception as e:
        logging.error(f"Error saving response to {worksheet_name}: {e}")

def fetch_questions():
    questions = fetch_data('Questions')
    CAT1_questions = [q[0] for q in questions if len(q) > 1 and q[1] == 'CAT1']
    CAT2_questions = [q[0] for q in questions if len(q) > 1 and q[1] == 'CAT2']
    logging.info(f"CAT1 Questions: {CAT1_questions}")
    logging.info(f"CAT2 Questions: {CAT2_questions}")
    return CAT1_questions, CAT2_questions

def fetch_bot_entries():
    entries = fetch_data('Bot Entries')
    CAT1_numbers = [entry[3] for entry in entries if len(entry) > 3 and entry[2].strip().upper() == 'CAT1']
    CAT2_numbers = [entry[3] for entry in entries if len(entry) > 3 and entry[2].strip().upper() == 'CAT2']
    logging.info(f"CAT1 Numbers: {CAT1_numbers}")
    logging.info(f"CAT2 Numbers: {CAT2_numbers}")
    return CAT1_numbers, CAT2_numbers

def send_next_question(phone_number, center, questions, sheet_name):
    if phone_number not in initial_greeting_sent:
        # Send initial greeting with the date and time
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        initial_greeting = f"Hi,\n\nToday's date and time is {now}.\n\nLet's get started with the questions."
        send_whatsapp_message(initial_greeting, phone_number)
        initial_greeting_sent[phone_number] = True
        current_question_index[phone_number] = 0  # Reset question index after greeting

    index = current_question_index.get(phone_number, 0)
    if index < len(questions):
        send_whatsapp_message(questions[index], phone_number)
        logging.info(f"Sent {center} question '{questions[index]}' to {phone_number}")
        current_question_index[phone_number] = index + 1
    else:
        # Send thank you message
        thank_you_message = "Thank you for your responses!"
        send_whatsapp_message(thank_you_message, phone_number)
        logging.info(f"Sent thank you message to {phone_number}")

def send_questions():
    CAT1_questions, CAT2_questions = fetch_questions()
    CAT1_numbers, CAT2_numbers = fetch_bot_entries()

    for number in CAT1_numbers:
        if number not in current_question_index:
            current_question_index[number] = 0
        send_next_question(number, 'CAT1', CAT1_questions, 'CAT1_Responses')

    for number in CAT2_numbers:
        if number not in current_question_index:
            current_question_index[number] = 0
        send_next_question(number, 'CAT2', CAT2_questions, 'CAT2_Responses')

@app.route("/")
def home():
    return "WhatsApp bot is running!"

@app.route("/receive_response", methods=['POST'])
def receive_response():
    logging.info("Received a response from Twilio.")
    from_number = request.values.get('From')
    body = request.values.get('Body')
    logging.info(f"From: {from_number}, Body: {body}")

    if from_number and body:
        from_number_without_prefix = from_number.split(':')[1]  # Extract the number without the prefix
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Identify the center and questions
        CAT1_questions, CAT2_questions = fetch_questions()
        CAT1_numbers, CAT2_numbers = fetch_bot_entries()

        logging.info(f"Received response from number: {from_number_without_prefix}")

        # Remove the +91 prefix from the incoming number for comparison
        from_number_without_country_code = from_number_without_prefix.replace('+91', '')

        if from_number_without_country_code in CAT1_numbers:
            center = 'CAT1'
            questions = CAT1_questions
            sheet_name = 'CAT1_Responses'
        elif from_number_without_country_code in CAT2_numbers:
            center = 'CAT2'
            questions = CAT2_questions
            sheet_name = 'CAT2_Responses'
        else:
            logging.error(f"Unknown number: {from_number}")
            return str(MessagingResponse())

        # Save the response
        question_index = current_question_index.get(from_number_without_country_code, 0) - 1
        if question_index < len(questions) and question_index >= 0:
            center_name = phone_to_center.get(from_number_without_country_code, "Unknown Center")
            response_data = [from_number, center_name, questions[question_index], body, now]
            save_response(sheet_name, response_data)
            logging.info(f"Saved response from {from_number} for question '{questions[question_index]}'")

            # Update the current question index and send the next question if available
            send_next_question(from_number_without_country_code, center, questions, sheet_name)

        resp = MessagingResponse()
        return str(resp)
    else:
        logging.error("Invalid data received from Twilio")
        return str(MessagingResponse())

if __name__ == "__main__":
    try:
        send_questions()  # Immediately send questions when the script is run
    except Exception as e:
        logging.error(f"An error occurred while sending questions: {e}")
    app.run(host='0.0.0.0', port=5000)  # Remove debug mode for production
