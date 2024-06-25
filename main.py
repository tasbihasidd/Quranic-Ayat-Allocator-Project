

from flask import Flask, request, jsonify, render_template, send_file
import pandas as pd
import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple, List
# from datetime import datetime
import datetime
from typing import List,Dict

# Load the csv files
df_quran = pd.read_csv('quran stats.csv')
df_allocate = pd.read_csv('names.csv')

# File to store the last allocation state
STATE_FILE = 'allocation_state.json'
ALLOCATED_CSV_FILE = 'allocated_ayats.csv'  # CSV file to store the allocation results

# Initialize Flask app
app = Flask(__name__)


def read_json_file(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data

def count_within_date_range(completion_dates: List[Dict[str, int]], start_date: datetime.date, end_date: datetime.date) -> int:
    
    total_count = 0
    for entry in completion_dates:
        entry_date = datetime.datetime.strptime(entry['date'], '%Y-%m-%d').date()
        if start_date <= entry_date <= end_date:
            total_count += entry['count']
    return total_count

def load_last_state(state_file: str, reset_state: bool = False) -> Tuple[int, int, str, int, List[dict]]:
    """ Load last state from JSON file """
    if not reset_state and os.path.exists(state_file):
        with open(state_file, 'r') as file:
            state = json.load(file)
            return (
                state.get('last_surah_index', 0),
                state.get('last_ayat_index', 0),
                state.get('last_surah_name', ''),
                state.get('quran_completed', 0),
                state.get('completion_dates', [])
            )
    return 0, 0, '', 0, []

def save_last_state(state_file: str, last_surah_index: int, last_ayat_index: int, last_surah_name: str, quran_completed: int, completion_dates: List[dict]) -> None:
    """ Save last state in the JSON file """
    state = {
        'last_surah_index': int(last_surah_index),
        'last_ayat_index': int(last_ayat_index),
        'last_surah_name': last_surah_name,
        'quran_completed': int(quran_completed),
        'completion_dates': completion_dates
    }
    with open(state_file, 'w') as file:
        json.dump(state, file)


def random_allocate_ayats(df_quran: pd.DataFrame, df_allocate: pd.DataFrame, ayats_per_person: int, start_surah_index: int = 0, start_ayat_index: int = 0, quran_completed: int = 0, completion_dates: List[dict] = []) -> Tuple[pd.DataFrame, int, int, str, int, List[dict]]:
    """ Allocate ayats to people randomly """
    current_surah_index = start_surah_index
    current_ayat_index = start_ayat_index
    last_surah_name = ''
    ayats_left = ayats_per_person

    for i, person in df_allocate.iterrows():
        ayat_list = []
        surah_list = []

        while ayats_left > 0:
            if current_surah_index >= len(df_quran):
                # Quran completion logic
                current_surah_index = 0
                current_ayat_index = 0
                quran_completed += 1
                completion_date = datetime.datetime.now().strftime('%Y-%m-%d')
                completion_dates.append({'date': completion_date, 'count': quran_completed})

            surah = df_quran.iloc[current_surah_index]
            surah_name = surah['Name of Surah']
            ayat_count = surah['No. of Ayat']

            ayats_to_allocate = min(ayats_left, ayat_count - current_ayat_index)
            if ayats_to_allocate > 0:
                ayat_start = current_ayat_index + 1
                ayat_end = current_ayat_index + ayats_to_allocate
                allocated_ayats = f"{ayat_start}-{ayat_end}"
                ayat_list.append(allocated_ayats)
                surah_list.append(surah_name)

                current_ayat_index += ayats_to_allocate
                ayats_left -= ayats_to_allocate

                if current_ayat_index >= ayat_count:
                    current_surah_index += 1
                    current_ayat_index = 0

        # Join the allocated ayats and surah names
        df_allocate.at[i, 'No. of Ayats Allocated'] = ', '.join(ayat_list)
        df_allocate.at[i, 'Surat name'] = ', '.join(surah_list)

        # Reset ayats_left for the next person
        ayats_left = ayats_per_person

    last_surah_name = surah_list[-1] if surah_list else ''  # Update last_surah_name based on the last surah allocated

    return df_allocate, current_surah_index, current_ayat_index, last_surah_name, quran_completed, completion_dates

def send_email(recipients: List[str], allocated_df: pd.DataFrame, quran_completed: int) -> str:
    """Send the allocation results via email."""

    # Email details
    sender_email = "hnhtechsolution02@gmail.com"
    password = "mqjyxutpycjisnnz"

    # Create email content
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = "Daily Ayat Allocation"
    body = f"<p>Quran completion count: {quran_completed}</p>" + allocated_df.to_html()

    msg.attach(MIMEText(body, 'html'))

    # Send email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, password)
        server.send_message(msg)
        server.quit()
        return "Email sent successfully!"
    except Exception as e:
        return f"Failed to send email: {e}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/allocate', methods=['POST'])
def allocate_and_send_email():
    """ Endpoint to allocate Ayats and send email """
    ayats_per_person_str = request.form.get('ayats_per_person')

    if not ayats_per_person_str:
        return jsonify({"error": "'ayats_per_person' is required."}), 400

    try:
        ayats_per_person = int(ayats_per_person_str)
    except ValueError:
        return jsonify({"error": "'ayats_per_person' must be a valid integer."}), 400
    
    recipients = request.form['recipients'].split(',')

    if not ayats_per_person or not recipients:
        return jsonify({"error": "Invalid request. 'ayats_per_person' and 'recipients' are required."}), 400

    # Load the last state from the state file with reset flag
    start_surah_index, start_ayat_index, last_surah_name, quran_completed, completion_dates = load_last_state(STATE_FILE)

    # Perform random allocation of Ayats starting from the loaded state
    allocated_df, last_surah_index, last_ayat_index, last_surah_name, quran_completed, completion_dates = random_allocate_ayats(df_quran, df_allocate, ayats_per_person, start_surah_index, start_ayat_index, quran_completed, completion_dates)

    # Save the current state to the state file for next run
    save_last_state(STATE_FILE, last_surah_index, last_ayat_index, last_surah_name, quran_completed, completion_dates)

    # Save the allocated DataFrame to a CSV file
    allocated_df.to_csv(ALLOCATED_CSV_FILE, index=False)

    # Send email with allocated results and Quran completion count
    email_result = send_email(recipients, allocated_df, quran_completed)

    # Include the download URL in the response
    download_url = request.host_url + 'download_csv'
    return jsonify({"message": email_result, "quran_completed": quran_completed, "completion_dates": completion_dates, "download_url": download_url})

@app.route('/download_csv')
def download_csv():
    """ Endpoint to download the allocated CSV file """
    return send_file(ALLOCATED_CSV_FILE, as_attachment=True, download_name='allocated_ayats.csv')

@app.route('/total_count', methods=['POST'])
def total_count():
    data = request.get_json()
    start_date = data['start_date']
    end_date = data['end_date']
    
    if not start_date or not end_date:
        return jsonify({"message": "Please provide both 'start_date' and 'end_date' as query parameters."}), 500

    try:
        start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"message": "Invalid date format. Please provide dates in 'YYYY-MM-DD' format."}), 500

    file_path = 'allocation_state.json'
    data = read_json_file(file_path)
       
    completion_dates = data.get('completion_dates')
    
    total_count = count_within_date_range(completion_dates, start_date, end_date)
    return jsonify({"status":True,"data":{"start_date": start_date, "end_date": end_date, "total_count": total_count}})

if __name__ == '__main__':
    app.run(debug=True)
