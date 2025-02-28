from flask import Flask, jsonify
from threading import Thread
import logging
import os
import time
import requests
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger('KeepAlive')
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask('')
start_time = time.time()

@app.route('/')
def home():
    """Основной эндпоинт для проверки работоспособности"""
    uptime = int(time.time() - start_time)
    return jsonify({
        "status": "alive",
        "uptime": f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/health')
def health():
    """Эндпоинт для проверки здоровья сервиса"""
    return jsonify({
        "status": "healthy",
        "memory_usage": os.popen('ps -o rss= -p %d' % os.getpid()).read().strip()
    })

def ping_self():
    """Функция для самопинга сервера"""
    while True:
        try:
            # Используем внешний URL вместо localhost
            port = int(os.environ.get('PORT', 8080))
            external_url = os.environ.get('EXTERNAL_URL', f'http://127.0.0.1:{port}')
            requests.get(external_url, timeout=30)
            logger.info("Self-ping successful")
        except Exception as e:
            logger.error(f"Self-ping failed: {str(e)}")
        time.sleep(60)  # уменьшим интервал до 1 минуты

def run():
    """Запуск Flask сервера"""
    try:
        port = int(os.environ.get('PORT', 8080))
        app.run(
            host='0.0.0.0',
            port=port,
            threaded=True,  # Включаем многопоточность
            debug=False     # Отключаем режим отладки
        )
    except Exception as e:
        logger.error(f"Failed to start on port {port}: {str(e)}")
        try:
            alt_port = 8000
            logger.info(f"Attempting to start on alternative port {alt_port}")
            app.run(
                host='0.0.0.0',
                port=alt_port,
                threaded=True,
                debug=False
            )
        except Exception as e2:
            logger.error(f"Failed to start on alternative port: {str(e2)}")
            raise

def keep_alive():
    """Запуск сервера и пинга в отдельных потоках"""
    try:
        # Запуск веб-сервера
        server_thread = Thread(target=run, daemon=True)
        server_thread.start()
        logger.info("Web server started successfully")

        # Запуск самопинга
        ping_thread = Thread(target=ping_self, daemon=True)
        ping_thread.start()
        logger.info("Self-ping service started")

    except Exception as e:
        logger.error(f"Failed to start keep-alive service: {str(e)}")
        raise
