from flask import Flask, request, jsonify, make_response
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask_cors import CORS
import requests
import logging
import re
import sys
from functools import wraps
import os
import json

ESP_IP_ADDRESS = os.getenv('ESP_IP_ADDRESS')  
if ESP_IP_ADDRESS is None:
    raise ValueError("No ESP IP address set. Please set the ESP_IP_ADDRESS environment variable.")

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

# Inicialize o aplicativo Flask
app = Flask(__name__)
CORS(app)

scheduler = BackgroundScheduler()
scheduler.start()

# Função para remover códigos ANSI
def strip_ansi_codes(s):
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', s)

class ANSIFilteredStdout:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout

    def write(self, text):
        filtered_text = strip_ansi_codes(text)
        self.original_stdout.write(filtered_text)

    def flush(self):
        self.original_stdout.flush()

sys.stdout = ANSIFilteredStdout(sys.stdout)

# Configuração de log
logging.basicConfig(level=logging.INFO)

# Configure o Flask logger
app.logger.setLevel(logging.INFO)

# Inicializar Firebase
cred = credentials.Certificate(FIREBASE_CRED_PATH)
firebase_admin.initialize_app(cred)
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
            return jsonify(response.json()), 200
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
    turn_on = data.get('turnOn')
    time_to_trigger = data.get('time')  # isso deve ser uma string no formato "HH:MM"

    hour, minute = map(int, time_to_trigger.split(":"))
    
    # Agenda a tarefa usando APScheduler
    scheduler.add_job(
        func=trigger_air_conditioner,
        trigger='date',
        run_date=datetime.datetime.now().replace(hour=hour, minute=minute),
        args=[turn_on],
        replace_existing=True
    )

    return jsonify({"message": "Scheduled successfully!"})

def trigger_air_conditioner(turn_on):
    # Aqui você pode fazer uma chamada HTTP para ligar/desligar o ar-condicionado
    # ou qualquer outra ação necessária.
    # Exemplo:
    action = "on" if turn_on else "off"
    try:
        if action == "on":
            response = requests.get(f"https://{ESP_IP_ADDRESS}/airconditioner/{action}")
        elif action == "off":
            response = requests.get(f"https://{ESP_IP_ADDRESS}/airconditioner/{action}")
    else:
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return jsonify({"error": "Failed to send command to ESP32."}), 500
    except requests.RequestException as e:
        logging.error(f'Erro ao enviar comando para o ESP32: {e}')
        return jsonify({"error": str(e)}), 500

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
    app.run(debug=True, host='0.0.0.0', port=5000)
