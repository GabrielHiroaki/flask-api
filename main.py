from flask import Flask, request, jsonify, make_response
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
import firebase_admin
from firebase_admin import db
import time
import hashlib
import hmac
import uuid
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

# Configuração com suas credenciais da API da Tuya
CLIENT_ID = '8gj9rsascg7aw7ptcynd'  # client_id fornecido pela Tuya.
SECRET = 'ab3646cb7fb448b6a73f28e2140975ec'  # segredo fornecido pela Tuya.
DEVICE_ID = '4530145050029107fb64'  # O ID do dispositivo que vamos controlar (tomada smart).
TUYA_ENDPOINT = 'https://openapi.tuyaus.com/v1.0/iot-03/devices/{}/commands'  # Endpoint da API para enviar comandos para o dispositivo.

# Variável global para armazenar o token de acesso (tomada smart).
ACCESS_TOKEN = None

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
# Referência para o Realtime Database
realtime_db_ref = db.reference()  

# Cliente do Firestore
firestore_db = firestore.client()

@app.route('/health_check', methods=['GET'])
def health_check():
    """Endpoint de verificação de saúde da API."""
    return jsonify({"Status": "API está ativa!"}), 200
    
@app.route('/sensor', methods=['GET'])
def get_sensor_data():
    """Endpoint para obter dados do sensor do ESP32."""
    userId = request.args.get('userId')  # Obtenha o userId da string de consulta
    
    if not userId:
        return jsonify({"error": "userId não fornecido."}), 400

    try:
        response = requests.get(f'https://{ESP_IP_ADDRESS}/sensor')
        if response.status_code == 200:
            data = response.json()

            sensor_data_ref = realtime_db_ref.child(f'users/{userId}/sensor_stats')  # Use o userId no caminho
            sensor_data_ref.set(data)

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
            raise ValueError("Nenhum dado do dispositivo fornecido!")
        user_devices_ref = firestore_db.collection('users').document(userId).collection('devices')
        new_doc_tuple = user_devices_ref.add(device_data)
        doc_ref = new_doc_tuple[1]
        return jsonify({"success": "Dispositivo adicionado com sucesso!", "id": doc_ref.id}), 201
    except Exception as e:
        logging.error(f"Erro ao adicionar o dispositivo para o usuário {userId}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices/<userId>/<deviceId>', methods=['DELETE'])
def delete_device(userId, deviceId):
    """Endpoint para excluir um dispositivo de um usuário."""
    try:
        user_devices_ref = firestore_db.collection('users').document(userId).collection('devices')
        device_ref = user_devices_ref.document(deviceId)
        device = device_ref.get()
        if device.exists:
            device_ref.delete()
            return jsonify({"message": "Dispositivo deletado com sucesso!"}), 200
        else:
            return jsonify({"error": "Dispositivo não encontrado!"}), 404
    except Exception as e:
        logging.error(f"Erro ao deletar o dispositivo para o usuário {userId} e ID do dispositivo {deviceId}: {e}")
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
            return jsonify({"error": "Comando não reconhecido!"}), 400

        if response.status_code == 200:
            return jsonify({"success": f"Comando do ar condicionado {command} executado com sucesso!"}), 200
        else:
            logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
            return jsonify({"error": "Falha ao enviar o comando para o ESP32!"}), 500
    except requests.RequestException as e:
        logging.error(f'Erro ao enviar comando para o ESP32: {e}')
        return jsonify({"error": str(e)}), 500


@app.route('/schedule_air_conditioner', methods=['POST'])
def schedule_air_conditioner():
    """Endpoint para gerenciar o agendamento do ar-condicionado."""
    data = request.json
    userId = data.get('userId')
    turn_on = data.get('turnOn')
    time_to_trigger = data.get('time')  # Pegando String no formato "HH:MM"

    try:
        # Converta a string "HH:MM" em data e hora
        dt = datetime.strptime(time_to_trigger, "%H:%M").time()
        timezone = pytz.timezone('America/Campo_Grande')
        now = datetime.now(timezone)
        
        # Se a hora agendada já passou, agendar para o próximo dia
        if now.time() <= dt:
            run_date = timezone.localize(datetime.combine(now.date(), dt))
        else:
            run_date = timezone.localize(datetime.combine(now.date() + timedelta(days=1), dt))

        schedule_data = {
            'turnOn': turn_on,
            'scheduledTime': time_to_trigger,
            'status': 'scheduled'
        }

        # Salva o agendamento no Firebase
        user_schedule_ref = realtime_db_ref.child(f'users/{userId}/air_conditioner_schedule')
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

        logging.info(f"Agendamento criado com sucesso. ID: {job.id} - Ligar: {turn_on} em {run_date}")
        return jsonify({"message": "Agendamento com sucesso!"}), 200
    except Exception as e:
        logging.error(f"Falha ao criar o agendamento: {e}")
        return jsonify({"message": "Falha ao efetuar o agendamento!"}), 500

def trigger_air_conditioner(userId, turn_on):
    logging.info(f"Função de gatilho chamada em: {datetime.now()}")
    try:
        action = 'ligar' if str(turn_on).lower() == "true" else 'desligar'
        response = requests.get(f"https://{ESP_IP_ADDRESS}/{action}")

        if response.status_code == 200:
            logging.info(f"Comando {action} enviado com sucesso para o ESP32.")
            realtime_db_ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'executed'})
        else:
            logging.error(f"Erro ao enviar comando para o ESP32. Status code: {response.status_code}")
            # Atualizando o valor 'turnOn' para false se houver um erro
            realtime_db_ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'error', 'turnOn': False})
    except requests.RequestException as e:
        logging.error(f'Erro ao enviar comando para o ESP32: {e}')
        # Atualizando também o valor 'turnOn' para false se houver uma exceção
        realtime_db_ref.child(f'users/{userId}/air_conditioner_schedule').update({'status': 'error', 'turnOn': False})


@app.route('/dispositivo/tv/energia', methods=['POST'])
def energia_tv():
    """Endpoint para ligar ou desligar a televisão."""
    response = requests.get(f'https://{ESP_IP_ADDRESS}/tv/energia')
    # Verifica se a solicitação foi bem-sucedida.
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text}), 200
    else:
        # Se a chamada para o ESP32 falhou, retorne um código de status de erro.
        # Isso refletirá a falha de volta ao aplicativo.
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return make_response(jsonify({"status": response.status_code, "mensagem": "Não foi possível ligar/desligar a tv"}), 500)
        
@app.route('/dispositivo/tv/volume/<acao>', methods=['POST'])
def controlar_volume(acao):
    """Endpoint para alterar o volume da televisão."""
    if acao not in ["mais", "menos"]:
        return jsonify({"error": "Ação inválida!"}), 400
        
    endpoint = f"/tv/volume/{acao}"
    response = requests.get(f'https://{ESP_IP_ADDRESS}{endpoint}')
    
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return jsonify({"error": "Falha ao enviar o comando para o ESP32!"}), 500
        
@app.route('/dispositivo/tv/canal/<acao>', methods=['POST'])
def mudar_canal(acao):
    """Endpoint para alterar o canal da televisão."""
    if acao not in ["mais", "menos"]:
        return jsonify({"error": "Ação inválida"}), 400

    endpoint = f"/tv/canal/{acao}"
    response = requests.get(f'https://{ESP_IP_ADDRESS}{endpoint}')
    
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return jsonify({"error": "Falha ao enviar o comando para o ESP32!"}), 500
        
@app.route('/dispositivo/tv/mudo', methods=['POST'])
def ativar_mudo():
    """Endpoint para ativar ou desativar o áudio da televisão."""
    response = requests.get(f'https://{ESP_IP_ADDRESS}/tv/mudo')

    # Verifica se a solicitação foi bem-sucedida.
    if response.status_code == 200:
        return jsonify({"status": response.status_code, "mensagem": response.text})
    else:
        # Se a chamada para o ESP32 falhou, retorne um código de status de erro.
        # Isso refletirá a falha de volta ao aplicativo.
        logging.error(f"Erro ao enviar comando para o ESP32. Código de status: {response.status_code}")
        return make_response(jsonify({"status": response.status_code, "mensagem": "Não foi possível ativar o mudo"}), 500)
        
@app.route('/dispositivo/led/on', methods=['GET'])
def turn_led_on():
    """Endpoint para ligar o LED."""
    try:
        # Enviar solicitação ao ESP para ligar o LED
        response = requests.get(f'https://{ESP_IP_ADDRESS}/led/on')
        if response.status_code == 200:
            return jsonify({'status': 'success', 'message': 'LED turned on'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to turn on LED'}), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/dispositivo/led/off', methods=['GET'])
def turn_led_off():
    """Endpoint para desligar o LED."""
    try:
        # Enviar solicitação ao ESP para ligar o LED
        response = requests.get(f'https://{ESP_IP_ADDRESS}/led/off')
        if response.status_code == 200:
            return jsonify({'status': 'success', 'message': 'LED turned off'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to turn off LED'}), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
        
# Função para obter o token de acesso da API da Tuya.
def get_token():
    global ACCESS_TOKEN  # Usa a variável global para armazenar o token recebido.
    method = 'GET'  # Método HTTP para a solicitação do token.
    timestamp = str(int(time.time() * 1000))  # Timestamp em milissegundos.
    sign_url = '/v1.0/token?grant_type=1'  # URL para solicitação de token.
    content_hash = hashlib.sha256(''.encode('utf-8')).hexdigest()  # Hash SHA256 do corpo da solicitação (vazio neste caso).
    string_to_sign = '\n'.join([method, content_hash, '', sign_url])  # Cria a string para assinar.
    sign_str = CLIENT_ID + timestamp + string_to_sign  # Concatena as informações para a assinatura.
    sign = hmac.new(SECRET.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest().upper()  # Gera a assinatura HMAC SHA256.

    headers = {
        'client_id': CLIENT_ID,
        'sign_method': 'HMAC-SHA256',
        't': timestamp,
        'sign': sign
    }
    response = requests.get(TUYA_ENDPOINT.replace('/v1.0/iot-03/devices/{}/commands', sign_url), headers=headers)  # Faz a solicitação HTTP GET para o endpoint.
    response_data = response.json()  # Converte a resposta em JSON.
    if response_data.get('success'):
        ACCESS_TOKEN = response_data['result']['access_token']  # Armazena o token de acesso se a solicitação for bem-sucedida.
    else:
        raise ValueError("Failed to get token: {}".format(response_data.get('msg')))  # Levanta um erro se a solicitação falhar.

# Função para criar a assinatura necessária para cada solicitação da API.
def get_signature(client_id, secret, access_token, method, path, body, t, nonce):
    content_sha256 = hashlib.sha256(body.encode('utf-8')).hexdigest() if body else hashlib.sha256(''.encode('utf-8')).hexdigest()  # Calcula o SHA256 do corpo da solicitação.
    string_to_sign = f"{method}\n{content_sha256}\n\n{path}"  # Cria a string para assinar.
    sign_str = f"{client_id}{access_token}{t}{nonce}{string_to_sign}"  # Concatena as informações com o token de acesso para a assinatura.
    signature = hmac.new(secret.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256).hexdigest().upper()  # Gera a assinatura HMAC SHA256.
    return signature  # Retorna a assinatura.

# Função para construir os cabeçalhos da solicitação com a assinatura incluída.
def get_headers(client_id, secret, access_token, method, path, body):
    t = str(int(time.time() * 1000))  # Gera o timestamp.
    nonce = str(uuid.uuid4())  # Gera um UUID para o nonce.
    sign = get_signature(client_id, secret, access_token, method, path, body, t, nonce)  # Obtém a assinatura.
    return {
        'client_id': client_id,
        'sign_method': 'HMAC-SHA256',
        't': t,
        'nonce': nonce,
        'sign': sign,
        'access_token': access_token,
        'Content-Type': 'application/json'
    }

# Rota do Flask para lidar com solicitações de envio de comando para o dispositivo.
@app.route('/send_command', methods=['POST'])
def send_command():
    global ACCESS_TOKEN  # Usa a variável global do token de acesso.
    if not ACCESS_TOKEN:
        get_token()  # Obtém ou atualiza o token de acesso se ele ainda não foi definido.
    body = json.dumps(request.json)  # Converte o corpo da solicitação para uma string JSON.
    method = 'POST'  # Método HTTP para a solicitação.
    path = f'/v1.0/iot-03/devices/{DEVICE_ID}/commands'  # Caminho da URL para o comando.
    headers = get_headers(CLIENT_ID, SECRET, ACCESS_TOKEN, method, path, body)  # Constrói os cabeçalhos para a solicitação.
    response = requests.post(TUYA_ENDPOINT.format(DEVICE_ID), headers=headers, data=body)  # Envia a solicitação POST para a API da Tuya.
    return response.json()  # Retorna a resposta como JSON.
    
    
# Rota do Flask para lidar com solicitações de status do dispositivo.
@app.route('/get_status', methods=['GET'])
def get_status():
    userId = request.args.get('userId')  # Obtenha o userId da string de consulta
    if not userId:
        return jsonify({"error": "userId não fornecido."}), 400
        
    global ACCESS_TOKEN  # Usa a variável global do token de acesso.
    if not ACCESS_TOKEN:
        get_token()  # Obtém ou atualiza o token de acesso se ele ainda não foi definido.
    method = 'GET'  # Método HTTP para a solicitação.
    path = f'/v1.0/iot-03/devices/{DEVICE_ID}/status'  # Caminho da URL para o status do dispositivo.
    headers = get_headers(CLIENT_ID, SECRET, ACCESS_TOKEN, method, path, '')  # Constrói os cabeçalhos para a solicitação.
    status_url = TUYA_ENDPOINT.format(DEVICE_ID).replace('commands', 'status')  # Ajusta o endpoint para a solicitação de status.
    response = requests.get(status_url, headers=headers)  # Envia a solicitação GET para a API da Tuya.
    # armazenar dados do consumo da tomada no banco de dados
    data = response.json()
    sensor_data_ref = realtime_db_ref.child(f'users/{userId}/outlet_stats')  # Use o userId no caminho
    sensor_data_ref.set(data)

    return response.json()  # Retorna a resposta como JSON.
    
# Tratamento de erros para rotas inexistentes
@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"error": "Endpoint não encontrado"}), 404
    
    return jsonify({"status": response.status_code, "mensagem": response.text})


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)  # Considere executar sem debug se possível

