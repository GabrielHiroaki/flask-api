from flask import Flask, request, jsonify
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

# Usa o dicionário para inicializar o Firebase
cred = credentials.Certificate(FIREBASE_CRED_PATH)
firebase_admin.initialize_app(cred)

ESP_IP_ADDRESS = os.getenv('ESP_IP_ADDRESS')  
if ESP_IP_ADDRESS is None:
    raise ValueError("No ESP IP address set. Please set the ESP_IP_ADDRESS environment variable.")

# Inicialize o aplicativo Flask
app = Flask(__name__)
CORS(app)

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
        response = requests.get(f'http://{ESP_IP_ADDRESS}/sensor')
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
    print(f'[DEBUG] Received command: {command}')
    """Endpoint para controlar o ar-condicionado via ESP32."""
    try:
        if command == "on":
            response = requests.get(f"http://{ESP_IP_ADDRESS}/ligar")
        elif command == "off":
            response = requests.get(f"http://{ESP_IP_ADDRESS}/desligar")
        elif "set_temperatura_" in command:
            temperatura = command.replace("set_temperatura_", "")
            response = requests.get(f"http://{ESP_IP_ADDRESS}/temperatura/{temperatura}")
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

#curl -X POST -d "comando=ligar" https://0554-2804-828-c230-ef8c-e007-fb80-ce0d-9f45.ngrok-free.app/dispositivo/luz/ligar
@app.route('/dispositivo/luz/ligar', methods=['POST'])
def ligar_luz():
    comando = request.form.get('comando')  # Extrair o comando do formulário
    
    app.logger.info(f"Comando recebido: {comando}")

    if comando == 'ligar':
        # Enviar um comando para o Arduino para ligar a luz
        arduino_url = f'http://{ESP_IP_ADDRESS}/acionar/luz'  # Substitua com a URL correta do seu Arduino
        app.logger.info(f"Enviando solicitação para: {arduino_url}")

        response = requests.post(arduino_url, data={'comando':'ligar'})  # Usar data para enviar formulário

        if response.status_code == 200:
            return jsonify({'mensagem': 'Luz foi ligada'})
        else:
            return jsonify({'mensagem': 'Falha ao ligar a luz', 'status': response.status_code}), response.status_code
    else:
        return jsonify({'mensagem': 'Comando não especificado', 'status': 400}), 400


@app.route('/dispositivo/luz/desligar', methods=['POST'])
def desligar_luz():
    comando = request.form.get('comando')  # Extrair o comando do formulário
    
    app.logger.info(f"Comando recebido: {comando}")

    if comando == 'desligar':
        # Enviar um comando para o Arduino para desligar a luz
        arduino_url = f'http://{ESP_IP_ADDRESS}/acionar/luz'  # Substitua com a URL correta do seu Arduino
        app.logger.info(f"Enviando solicitação para: {arduino_url}")

        response = requests.post(arduino_url, data={'comando':'desligar'})  # Usar data para enviar formulário

        if response.status_code == 200:
            return jsonify({'mensagem': 'Luz foi desligada'})
        else:
            return jsonify({'mensagem': 'Falha ao desligar a luz', 'status': response.status_code}), response.status_code
    else:
        return jsonify({'mensagem': 'Comando não especificado', 'status': 400}), 400

#curl -X POST -d "comando=ligar" https://0554-2804-828-c230-ef8c-e007-fb80-ce0d-9f45.ngrok-free.app/dispositivo/tomada/ligar
@app.route('/dispositivo/tomada/ligar', methods=['POST'])
def ligar_tomada():
    comando = request.form.get('comando')  # Extrair o comando do formulário
    
    app.logger.info(f"Comando recebido: {comando}")

    if comando == 'ligar':
        # Enviar um comando para o Arduino para ligar a tomada
        arduino_url = f'http://{ESP_IP_ADDRESS}/acionar/tomada'  # Substitua com a URL correta do seu Arduino
        app.logger.info(f"Enviando solicitação para: {arduino_url}")

        response = requests.post(arduino_url, data={'comando':'ligar'})  # Usar data para enviar formulário

        if response.status_code == 200:
            return jsonify({'mensagem': 'Tomada foi ligada'})
        else:
            return jsonify({'mensagem': 'Falha ao ligar a tomada', 'status': response.status_code}), response.status_code
    else:
        return jsonify({'mensagem': 'Comando não especificado', 'status': 400}), 400

@app.route('/dispositivo/tomada/desligar', methods=['POST'])
def desligar_tomada():
    comando = request.form.get('comando')  # Extrair o comando do formulário
    
    app.logger.info(f"Comando recebido: {comando}")

    if comando == 'desligar':
        # Enviar um comando para o Arduino para desligar a tomada
        arduino_url = f'http://{ESP_IP_ADDRESS}/acionar/tomada'  # Substitua com a URL correta do seu Arduino
        app.logger.info(f"Enviando solicitação para: {arduino_url}")

        response = requests.post(arduino_url, data={'comando':'desligar'})  # Usar data para enviar formulário

        if response.status_code == 200:
            return jsonify({'mensagem': 'Tomada foi desligada'})
        else:
            return jsonify({'mensagem': 'Falha ao desligar a tomada', 'status': response.status_code}), response.status_code
    else:
        return jsonify({'mensagem': 'Comando não especificado', 'status': 400}), 400


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
