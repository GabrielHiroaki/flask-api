from flask import Flask, request, jsonify, make_response
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
import firebase_admin
from firebase_admin import db
import time
from firebase_admin import credentials, firestore, auth
from flask_cors import CORS
import requests
import logging
import re
import sys
from functools import wraps
import os
import json


# Constantes
FIREBASE_CRED_PATH = {
    "type": os.environ.get("type"),
    "project_id": os.environ.get("project_id"),
    "private_key_id": os.environ.get("private_key_id"),
    "private_key": os.environ.get("private_key").replace('\\n', '\n'),  # Para tratar quebras de linha na chave privada
    "client_email": os.environ.get("client_email"),
    "client_id": os.environ.get("client_id"),
    "auth_uri": os.environ.get("auth_uri"),
    "token_uri": os.environ.get("token_uri"),
    "auth_provider_x509_cert_url": os.environ.get("auth_provider_x509_cert_url"),
    "client_x509_cert_url": os.environ.get("client_x509_cert_url"),
    # Adicione outros campos se necessário
}
ESP_IP_ADDRESS = os.getenv('ESP_IP_ADDRESS')  
if ESP_IP_ADDRESS is None:
    raise ValueError("No ESP IP address set. Please set the ESP_IP_ADDRESS environment variable.")
    
# Inicialize o aplicativo Flask
app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Campo_Grande'))
scheduler.start()
CORS(app)

# Configurar o fuso horário do servidor para Campo Grande / Mato Grosso do Sul
os.environ['TZ'] = 'America/Campo_Grande'
time.tzset()
    
# Imprimir o fuso horário do servidor
print('Horário Servidor: ', time.tzname)

# Se desejar verificar o horário UTC atual
utc_now = datetime.now(pytz.utc)
print('Horário UTC atual: ', utc_now)

# Se desejar verificar o horário atual em Campo Grande / Mato Grosso do Sul
local_now = datetime.now(pytz.timezone('America/Campo_Grande'))
print('Horário Campo Grande / Mato Grosso do Sul atual: ', local_now)

# Configuração de log
logging.basicConfig(level=logging.INFO)

# Configure o Flask logger
app.logger.setLevel(logging.INFO)

# Inicializar Firebase
cred = credentials.Certificate(FIREBASE_CRED_PATH)
# firebase_admin.initialize_app(cred)
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://aplicativo-5310e-default-rtdb.firebaseio.com/'
})
ref = db.reference()  # Referência para o Realtime Database
db = firestore.client()

@app.route('/health_check', methods=['GET'])
def health_check():
    """Endpoint de verificação de saúde da API."""
    return jsonify({"Status": "API is up and running!"}), 200

@app.route('/sensor', methods=['GET'])
def get_sensor_data():
    """Endpoint para obter dados do sensor do ESP32."""
    try:
        response = requests.get(f'https://{ESP_IP_ADDRESS}/sensor')
        if response.status_code == 200:
            data = response.json()

            # Armazene os dados no Realtime Database
            ref = db.reference('sensor_data')
            ref.push(data)

            return jsonify(data), 200
        else:
            logging.error(f"Erro ao buscar dados do sensor do ESP32. Código de status: {response.status_code}")
            return jsonify({"error": "Não foi possível buscar os dados do sensor do ESP32."}), 500
    except requests.RequestException as e:
        logging.error(f'Erro ao buscar dados do sensor: {e}')
        return jsonify({"error": str(e)}), 500

@app.route('/devices/<userId>', methods=['POST'])
def add_device(userId):
    """Endpoint para adicionar um novo dispositivo para um usuário."""
    try:
        device_data = request.get_json()
        if not device_data:
            raise ValueError("No device data provided")
        user_devices_ref = db.collection('users').document(userId).collection('devices')
        new_doc_tuple = user_devices_ref.add(device_data)
        doc_ref = new_doc_tuple[1]
        return jsonify({"success": "Device added successfully", "id": doc_ref.id}), 201
    except Exception as e:
        logging.error(f"Error adding device for user {userId}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices/<userId>/<deviceId>', methods=['DELETE'])
def delete_device(userId, deviceId):
    """Endpoint para excluir um dispositivo de um usuário."""
    try:
        user_devices_ref = db.collection('users').document(userId).collection('devices')
        device_ref = user_devices_ref.document(deviceId)
        device = device_ref.get()
        if device.exists:
            device_ref.delete()
            return jsonify({"message": "Device deleted successfully"}), 200
        else:
            return jsonify({"error": "Device not found"}), 404
    except Exception as e:
        logging.error(f"Error deleting device for user {userId} and device ID {deviceId}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/airconditioner/<command>', methods=['POST'])
def control_airconditioner(command):
    """Endpoint para controlar o ar-condicionado via ESP32."""
    try:
        if command == "on":
            response = requests.get(f"https://{ESP_IP_ADDRESS}/ligar")
        elif command == "off":
            response = requests.get(f"https://{ESP_IP_ADDRESS}/desligar")
        elif "set_temperatura_" in command:
            temperatura = command.replace("set_temperatura_", "")
            response = requests.get(f"https://{ESP_IP_ADDRESS}/temperatura/{temperatura}")
        else:
            return jsonify({"error": "Command not recognized"}), 400

        if response.status_code == 200:
            return jsonify({"success": f"Air conditioner command {command} executed successfully"}), 200
        else:
            logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
            return jsonify({"error": "Failed to send command to ESP32."}), 500
    except requests.RequestException as e:
        logging.error(f'Erro ao enviar comando para o ESP32: {e}')
        return jsonify({"error": str(e)}), 500


@app.route('/schedule_air_conditioner', methods=['POST'])
def schedule_air_conditioner():
    data = request.json
    userId = data.get('userId')
    turn_on = data.get('turnOn')
    time_to_trigger = data.get('time')  # This should be a string in the format "HH:MM"

    try:
        # Convert the "HH:MM" string to datetime
        dt = datetime.strptime(time_to_trigger, "%H:%M").time()
        now = datetime.now(pytz.timezone('America/Campo_Grande'))
        
        # Se a hora agendada já passou, agendar para o próximo dia
        run_date = datetime.now() if now.time() <= dt else now + timedelta(days=1)
        run_date = run_date.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)

        schedule_data = {
            'turnOn': turn_on,
            'scheduledTime': time_to_trigger,
            'status': 'scheduled'
        }

        # Salva o agendamento no Firebase
        user_schedule_ref = ref.child(f'users/{userId}/air_conditioner_schedule')
        user_schedule_ref.set(schedule_data)

        # Agendar a função de trigger
        job = scheduler.add_job(
            func=trigger_air_conditioner,
            trigger='date',
            run_date=run_date,
            args=[userId, turn_on],
            id=f"{userId}_ac_schedule",  # ID único
            replace_existing=True
        )

        logging.info(f"Schedule created successfully. ID: {job.id} - Turn on: {turn_on} at {run_date}")
        return jsonify({"message": "Scheduled successfully!"}), 200
    except Exception as e:
        logging.error(f"Failed to create schedule: {e}")
        return jsonify({"message": "Failed to schedule."}), 500

def trigger_air_conditioner(userId, turn_on):
    logging.info(f"Trigger function called at: {datetime.now()}")
    try:
        action = 'ligar' if turn_on == "true" else 'desligar'
        # Certifique-se de que o ESP_IP_ADDRESS está definido corretamente
        response = requests.get(f"https://{ESP_IP_ADDRESS}/{action}")

        if response.status_code == 200:
            logging.info(f"Command {action} sent successfully to the ESP32.")
            ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'executed'})
        else:
            logging.error(f"Error sending command to the ESP32. Status code: {response.status_code}")
            # Updating the 'turnOn' value to false if there's an error
            ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'error', 'turnOn': False})
    except requests.RequestException as e:
        logging.error(f'Error sending command to the ESP32: {e}')
        # Also updating the 'turnOn' value to false if there's an exception
        ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'error', 'turnOn': False})


@app.route('/airconditioner_state/<userId>', methods=['GET'])
def get_airconditioner_state(userId):
    """Endpoint para obter o estado atual do ar-condicionado."""
    try:
        # Usando o caminho fornecido com o UID dinâmico
        state_ref = ref.child(f'users/{userId}/air_conditioner_schedule/turnOn')
        state = state_ref.get()  # Pega o estado atual

        # Retorna o estado
        return jsonify({"turnOn": state})

    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/dispositivo/tv/energia', methods=['POST'])
def energia_tv():
    response = requests.get(f'https://{ESP_IP_ADDRESS}/tv/energia')
    # Verifica se a solicitação foi bem-sucedida.
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text}), 200
    else:
        # Se a chamada para o Arduino falhou, retorne um código de status de erro.
        # Isso refletirá a falha de volta ao aplicativo.
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return make_response(jsonify({"status": response.status_code, "mensagem": "Não foi possível ligar/desligar a tv"}), 500)
        
@app.route('/dispositivo/tv/volume/<acao>', methods=['POST'])
def controlar_volume(acao):
    if acao not in ["mais", "menos"]:
        return jsonify({"error": "Ação inválida"}), 400
        
    endpoint = f"/tv/volume/{acao}"
    response = requests.get(f'https://{ESP_IP_ADDRESS}{endpoint}')
    
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return jsonify({"error": "Failed to send command to ESP32."}), 500
        
@app.route('/dispositivo/tv/canal/<acao>', methods=['POST'])
def mudar_canal(acao):
    if acao not in ["mais", "menos"]:
        return jsonify({"error": "Ação inválida"}), 400

    endpoint = f"/tv/canal/{acao}"
    response = requests.get(f'https://{ESP_IP_ADDRESS}{endpoint}')
    
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return jsonify({"error": "Failed to send command to ESP32."}), 500
        
@app.route('/dispositivo/tv/mudo', methods=['POST'])
def ativar_mudo():
    response = requests.get(f'https://{ESP_IP_ADDRESS}/tv/mudo')

    # Verifica se a solicitação foi bem-sucedida.
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        # Se a chamada para o Arduino falhou, retorne um código de status de erro.
        # Isso refletirá a falha de volta ao aplicativo.
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return make_response(jsonify({"status": response.status_code, "mensagem": "Não foi possível ativar o mudo"}), 500)
        
# Tratamento de erros para rotas inexistentes
@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"error": "Endpoint não encontrado"}), 404
    
    return jsonify({"status": response.status_code, "mensagem": response.text})


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)  # Considere executar sem debug se possível

