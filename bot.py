from instagrapi import Client
from keep_alive import keep_alive
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, LabeledPrice, Invoice, PreCheckoutQuery
from telegram.ext import PreCheckoutQueryHandler
import logging
import time
from datetime import datetime, timedelta
import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading
from functools import partial
import queue
import socket
import dns.resolver
import requests.packages.urllib3.util.connection as urllib3_cn
from keep_alive import keep_alive

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   level=logging.INFO)
logger = logging.getLogger(__name__)

# Добавляем запись логов в файл
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Настройки для повторных попыток
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

# Конфигурация
TELEGRAM_TOKEN = '8003575140:AAHeQbGBFrOmd-L_gvWqhR3jhG1RAgpn30Q'
INSTAGRAM_USERNAME = 'needsomev11be'
INSTAGRAM_PASSWORD = '5621456xasa'

# Настройка клиента Instagram
cl = Client()
cl.delay_range = [2, 5]
cl.request_timeout = 30
cl.download_timeout = 60

# Настраиваем сессию и куки
try:
    if os.path.exists('session.json'):
        cl.load_settings('session.json')
        if not cl.login_by_sessionid(cl.sessionid):
            raise Exception("Invalid session")
    else:
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        cl.dump_settings('session.json')
    
    # Проверяем валидность сессии
    cl.get_timeline_feed()
    logger.info("Успешно авторизовались в Instagram")
except Exception as e:
    logger.error(f"Ошибка входа в Instagram: {str(e)}")
    if os.path.exists('session.json'):
        os.remove('session.json')
    cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
    cl.dump_settings('session.json')

# Словари для хранения данных пользователей
user_subscriptions = {}  # {user_id: [instagram_usernames]}
last_posts = {}  # {user_id: {instagram_username: last_post_date}}
last_stories = {}  # {user_id: {instagram_username: last_story_id}}

# В начало файла добавим настройки
MAX_WORKERS = 4
QUEUE_SIZE = 100
RETRY_DELAY = 5
MAX_RETRIES = 3
task_queue = Queue(maxsize=QUEUE_SIZE)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Добавляем блокировки для потокобезопасности
data_lock = threading.Lock()

# Добавим константы для платежей
PROVIDER_TOKEN = '1744374395:TEST:5621456xasa'  # Замените на ваш токен от @BotFather
CURRENCY = 'USD'

# Обновим словарь цен, добавив описания для платежей
SUBSCRIPTION_PRICES = {
    '1month': {
        'price': 149,
        'title': '⭐️ Подписка на 1 месяц',
        'description': '30 дней доступа к отслеживанию Instagram историй',
    },
    '3months': {
        'price': 349,
        'title': '⭐️ Подписка на 3 месяца (-25%)',
        'description': '90 дней доступа к отслеживанию Instagram историй',
    },
    '6months': {
        'price': 599,
        'title': '⭐️ Подписка на 6 месяцев (-36%)',
        'description': '180 дней доступа к отслеживанию Instagram историй',
    },
    '1year': {
        'price': 999,
        'title': '⭐️ Подписка на 1 год (-48%)',
        'description': '365 дней доступа к отслеживанию Instagram историй',
    }
}

# В начале файла, после других глобальных переменных
user_subscriptions_data = {}  # Инициализируем глобальную переменную

def create_invoice(plan):
    """Создание инвойса для оплаты"""
    plan_data = SUBSCRIPTION_PRICES[plan]
    return Invoice(
        title=plan_data['title'],
        description=plan_data['description'],
        start_parameter=f'sub_{plan}',
        currency=CURRENCY,
        prices=[LabeledPrice(plan_data['label'], plan_data['price'] * 100)]  # Цена в центах
    )

# Настройки для DNS резолвинга
dns_resolver = dns.resolver.Resolver()
dns_resolver.nameservers = ['8.8.8.8', '8.8.4.4']  # Google DNS

def get_instagram_ip():
    """Получение IP адреса Instagram"""
    try:
        answers = dns_resolver.resolve('i.instagram.com', 'A')
        return str(answers[0])
    except Exception as e:
        logger.error(f"Ошибка при получении IP Instagram: {str(e)}")
        return None

def setup_instagram_client():
    """Настройка клиента Instagram"""
    try:
        # Настройка сессии
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Получаем IP Instagram
        instagram_ip = get_instagram_ip()
        if instagram_ip:
            logger.info(f"Получен IP адрес Instagram: {instagram_ip}")
            session.headers.update({'Host': 'i.instagram.com'})
            session.mount(f"https://{instagram_ip}", adapter)

        # Настраиваем клиент
        cl.delay_range = [1, 3]
        cl.request_timeout = 10
        cl.download_timeout = 20
        cl.session = session

        # Проверяем авторизацию
        if os.path.exists('session.json'):
            cl.load_settings('session.json')
            if not cl.login_by_sessionid(cl.sessionid):
                raise Exception("Invalid session")
        else:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            cl.dump_settings('session.json')
        
        # Проверяем подключение
        cl.get_timeline_feed()
        logger.info("✅ Успешно авторизовались в Instagram")
        
        # Инициализируем файлы и структуры данных сразу после успешной авторизации
        initialize_files()
        load_user_data()
        load_subscription_data()
        
        # Создаем глобальные структуры данных, если они пустые
        global user_subscriptions, last_posts, last_stories, user_subscriptions_data
        if not user_subscriptions:
            user_subscriptions = {}
        if not last_posts:
            last_posts = {}
        if not last_stories:
            last_stories = {}
        if not user_subscriptions_data:
            user_subscriptions_data = {}
            
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка настройки клиента Instagram: {str(e)}")
        if os.path.exists('session.json'):
            os.remove('session.json')
        return False

def log_user_action(user_id, action, details=None):
    """Логирование действий пользователя"""
    username = f"user_{user_id}"
    if details:
        logger.info(f"👤 {username} - {action}: {details}")
    else:
        logger.info(f"👤 {username} - {action}")

def log_bot_action(action, details=None):
    """Логирование действий бота"""
    if details:
        logger.info(f"🤖 Bot - {action}: {details}")
    else:
        logger.info(f"🤖 Bot - {action}")

def load_user_data():
    """Потокобезопасная загрузка данных пользователей"""
    global user_subscriptions, last_posts, last_stories
    
    with data_lock:
        try:
            if os.path.exists('user_data.json') and os.path.getsize('user_data.json') > 0:
                with open('user_data.json', 'r') as f:
                    data = json.load(f)
                    user_subscriptions = data.get('subscriptions', {})
                    last_posts = data.get('posts', {})
                    last_stories = data.get('stories', {})
            else:
                # Создаем новый файл с пустыми данными
                user_subscriptions = {}
                last_posts = {}
                last_stories = {}
                save_user_data()
                logger.info("Создан новый файл данных пользователей")
        except Exception as e:
            logger.error(f"Ошибка загрузки данных пользователей: {str(e)}")
            # В случае ошибки инициализируем пустые структуры
            user_subscriptions = {}
            last_posts = {}
            last_stories = {}
            # И пытаемся сохранить их
            try:
                save_user_data()
            except Exception as save_error:
                logger.error(f"Ошибка сохранения данных пользователей: {str(save_error)}")

def save_user_data():
    """Потокобезопасное сохранение данных пользователей"""
    with data_lock:
        try:
            data = {
                'subscriptions': user_subscriptions,
                'posts': last_posts,
                'stories': last_stories
            }
            with open('user_data.json', 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных пользователей: {str(e)}")

def load_subscription_data():
    """Загрузка данных о подписках"""
    global user_subscriptions_data
    try:
        if os.path.exists('subscriptions.json'):
            with open('subscriptions.json', 'r') as f:
                user_subscriptions_data = json.load(f)
            logger.info("Данные о подписках загружены")
        else:
            user_subscriptions_data = {}
            logger.info("Создан новый файл подписок")
            save_subscription_data()
    except Exception as e:
        logger.error(f"Ошибка загрузки данных о подписках: {str(e)}")
        user_subscriptions_data = {}

def save_subscription_data():
    """Сохранение данных о подписках"""
    try:
        with open('subscriptions.json', 'w') as f:
            json.dump(user_subscriptions_data, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных о подписках: {str(e)}")

def check_subscription(user_id):
    """Проверка активной подписки"""
    try:
        user_id = str(user_id)
        if user_id not in user_subscriptions_data:
            logger.info(f"Пользователь {user_id} не найден в данных подписок")
            return False
        
        expires = datetime.fromtimestamp(user_subscriptions_data[user_id]['expires'])
        is_active = expires > datetime.now()
        is_trial = user_subscriptions_data[user_id].get('is_trial', False)
        
        if is_active:
            if is_trial:
                logger.info(f"Активна пробная подписка для {user_id}, истекает {expires}")
            else:
                logger.info(f"Активна платная подписка для {user_id}, истекает {expires}")
        else:
            logger.info(f"Подписка истекла для {user_id}")
            
        return is_active
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки {user_id}: {str(e)}")
        return False

def get_subscription_keyboard():
    """Клавиатура с тарифами"""
    keyboard = [
        [InlineKeyboardButton("1 месяц - 149 ⭐️", callback_data='sub_1month')],
        [InlineKeyboardButton("3 месяца - 349 ⭐️ (-25%)", callback_data='sub_3months')],
        [InlineKeyboardButton("6 месяцев - 599 ⭐️ (-36%)", callback_data='sub_6months')],
        [InlineKeyboardButton("1 год - 999 ⭐️ (-48%)", callback_data='sub_1year')],
        [InlineKeyboardButton("« Назад", callback_data='back_to_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def show_subscription_info(update, context):
    """Показать информацию о подписке"""
    if isinstance(update, CallbackQuery):
        user_id = str(update.from_user.id)
        chat_id = update.message.chat_id
    else:
        user_id = str(update.effective_user.id)
        chat_id = update.message.chat_id

    try:
        if check_subscription(user_id):
            expires = datetime.fromtimestamp(user_subscriptions_data[user_id]['expires'])
            days_left = (expires - datetime.now()).days
            plan = user_subscriptions_data[user_id]['plan']
            is_trial = user_subscriptions_data[user_id].get('is_trial', False)
            
            if is_trial:
                message = (
                    f"✅ *У вас активна пробная подписка*\n"
                    f"⏳ Осталось дней: {days_left}\n"
                    f"📆 Истекает: {expires.strftime('%d.%m.%Y')}\n\n"
                    f"🔥 Чтобы продолжить пользоваться ботом после пробного периода,\n"
                    f"выберите один из тарифов:"
                )
            else:
                message = (
                    f"✅ *У вас активная подписка*\n"
                    f"📅 Тариф: {plan}\n"
                    f"⏳ Осталось дней: {days_left}\n"
                    f"📆 Истекает: {expires.strftime('%d.%m.%Y')}\n\n"
                    f"Вы можете продлить подписку в любой момент:"
                )
        else:
            message = (
                "🎟️ *Выберите тариф*\n\n"
                "‣ *1 месяц* (30 дней) — 149 ⭐️\n"
                "  ( ~ $2.99 / 280₽ )\n\n"
                "‣ *3 месяца* (90 дней) — 447 349 ⭐️\n"
                "  ( ~ $6.99 / 640₽, экономия 25% )\n"
                "  ( ~ $2.33 / 210₽ в месяц )\n\n"
                "‣ *6 месяцев* (180 дней) — 894 599 ⭐️\n"
                "  ( ~ $11.98 / 1100₽, экономия 36% )\n"
                "  ( ~ $1.99 / 180₽ в месяц )\n\n"
                "‣ *1 год* (365 дней) — 1788 999 ⭐️\n"
                "  ( ~ $19.99 / 1800₽, экономия 48% )\n"
                "  ( ~ $1.67 / 150₽ в месяц )\n\n"
                "💳 Оплата через Telegram Stars\n"
                "🔄 Автопродление отключено\n"
                "💡 Купить звёзды: @PremiumBot"
            )
        
        if isinstance(update, CallbackQuery):
            update.edit_message_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=get_subscription_keyboard()
            )
        else:
            update.message.reply_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=get_subscription_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка при показе информации о подписке: {str(e)}")
        error_text = "❌ Произошла ошибка при получении информации о подписке"
        if isinstance(update, CallbackQuery):
            update.edit_message_text(text=error_text, reply_markup=get_back_to_menu_keyboard())
        else:
            update.message.reply_text(text=error_text, reply_markup=get_back_to_menu_keyboard())

def get_main_menu_keyboard():
    """Получение основной клавиатуры меню"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить аккаунт", callback_data='add_account')],
        [InlineKeyboardButton("📋 Мои подписки", callback_data='list_subscriptions')],
        [InlineKeyboardButton("📥 Загрузить текущие истории", callback_data='load_stories')],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')],
        [InlineKeyboardButton("💵 Подписка", callback_data='subscription_info')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_menu_keyboard():
    """Клавиатура с кнопкой возврата в меню"""
    keyboard = [[InlineKeyboardButton("« Назад в меню", callback_data='back_to_menu')]]
    return InlineKeyboardMarkup(keyboard)

def start(update, context):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    log_user_action(user_id, "Запустил бота")
    
    # Проверяем, новый ли это пользователь
    is_new_user = (user_id not in user_subscriptions) and (user_id not in user_subscriptions_data)
    logger.info(f"Проверка нового пользователя {user_id}: {is_new_user}")
    
    if is_new_user:
        logger.info(f"Инициализация данных для нового пользователя {user_id}")
        # Инициализируем базовые структуры
        user_subscriptions[user_id] = []
        last_posts[user_id] = {}
        last_stories[user_id] = {}
        save_user_data()
        
        # Добавляем пробную подписку на 7 дней
        expires = datetime.now() + timedelta(days=7)
        with data_lock:
            user_subscriptions_data[user_id] = {
                'expires': expires.timestamp(),
                'plan': 'trial',
                'is_trial': True
            }
            save_subscription_data()
            logger.info(f"Создана пробная подписка для пользователя {user_id}")
        
        welcome_message = (
            "👋 Добро пожаловать в Instagram Monitor Bot!\n\n"
            "🎁 Вам доступна *бесплатная пробная подписка на 7 дней*!\n\n"
            "🔍 Бот будет следить за выбранными вами Instagram аккаунтами и сообщать о новых:\n"
            "📸 Постах\n"
            "🎥 Историях\n\n"
            "❗️ Для начала работы используйте команду /auth для подключения к Instagram\n\n"
            "Выберите действие:"
        )
        log_bot_action("Создан новый пользователь с пробной подпиской", f"user_id: {user_id}")
    else:
        welcome_message = (
            "👋 Добро пожаловать в Instagram Monitor Bot!\n\n"
            "🔍 Я буду следить за выбранными вами Instagram аккаунтами и сообщать о новых:\n"
            "📸 Постах\n"
            "🎥 Историях\n\n"
            "❗️ Если бот не подключен к Instagram, используйте команду /auth\n\n"
            "Выберите действие:"
        )

    update.message.reply_text(
        text=welcome_message,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

def help_command(update, context):
    """Обработчик команды /help"""
    message = (
        "📚 *Доступные команды:*\n\n"
        "/start - Запустить бота\n"
        "/add username - Добавить Instagram аккаунт для отслеживания\n"
        "/remove username - Удалить аккаунт из отслеживания\n"
        "/list - Показать список отслеживаемых аккаунтов\n"
        "/loadstories - Загрузить все текущие истории\n"
        "/help - Показать это сообщение\n\n"
        "❗️ *Примечание:* Бот проверяет обновления каждую минуту"
    )
    update.message.reply_text(message, parse_mode='Markdown')

def get_user_id_by_username(username):
    """Получение user_id по имени пользователя"""
    cl.user_id_from_username(username)
    return cl.user_id_from_username(username)

def get_stories(username):
    """Получение историй пользователя"""
    try:
        # Получаем ID пользователя
        user_id = cl.user_id_from_username(username)
        logger.info(f"Получен user_id {user_id} для {username}")
        
        # Получаем истории
        try:
            stories = cl.user_stories(user_id)
            if stories:
                logger.info(f"Успешно получено {len(stories)} историй для {username}")
                return stories
            else:
                logger.info(f"Нет активных историй у пользователя {username}")
                return []
        except Exception as e:
            logger.error(f"Ошибка при получении историй для {username}: {str(e)}")
            return []
            
    except Exception as e:
        logger.error(f"Ошибка при получении user_id для {username}: {str(e)}")
        return []

def download_and_send_story(story, username, user_id, temp_dir, context):
    """Скачивание и отправка одной истории"""
    try:
        # Проверяем, не отправляли ли мы уже эту историю
        if user_id in last_stories and username in last_stories[user_id]:
            if story.pk in last_stories[user_id][username]:
                log_bot_action("История уже была отправлена", f"story_id: {story.pk}, аккаунт: {username}")
                return False
        
        log_bot_action("Начало скачивания истории", f"story_id: {story.pk}, аккаунт: {username}")
        
        # Создаем директорию если её нет
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        file_path = os.path.join(temp_dir, f"story_{story.pk}")
        
        try:
            if story.media_type == 1:  # Фото
                file_path += ".jpg"
                url = story.thumbnail_url
            else:  # Видео
                file_path += ".mp4"
                url = story.video_url

            # Пробуем скачать напрямую
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                log_bot_action("Успешно скачан файл", f"story_id: {story.pk}, размер: {len(response.content)}")
            else:
                # Если не получилось, используем API
                log_bot_action("Прямое скачивание не удалось, использую API", f"story_id: {story.pk}")
                cl.story_download(story.pk, folder=temp_dir)

        except Exception as e:
            log_bot_action("Ошибка при скачивании", f"story_id: {story.pk}, ошибка: {str(e)}")
            return False

        # Проверяем файл
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            log_bot_action("Ошибка скачивания", f"story_id: {story.pk}, файл не создан или пустой")
            return False

        # Отправляем файл
        try:
            if story.media_type == 1:
                context.bot.send_photo(
                    chat_id=user_id,
                    photo=open(file_path, 'rb'),
                    caption=f"История от @{username}"
                )
            else:
                context.bot.send_video(
                    chat_id=user_id,
                    video=open(file_path, 'rb'),
                    caption=f"История от @{username}"
                )
            log_bot_action("История успешно отправлена", f"story_id: {story.pk}, пользователю: {user_id}")

            # Если успешно отправили, сохраняем ID истории
            if user_id not in last_stories:
                last_stories[user_id] = {}
            if username not in last_stories[user_id]:
                last_stories[user_id][username] = set()
            last_stories[user_id][username].add(story.pk)
            save_user_data()  # Сохраняем данные
            
            return True
        except Exception as e:
            log_bot_action("Ошибка отправки", f"story_id: {story.pk}, ошибка: {str(e)}")
            return False
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
                
    except Exception as e:
        log_bot_action("Критическая ошибка", f"story_id: {story.pk}, ошибка: {str(e)}")
        return False

def add_account(update, context):
    """Добавление нового аккаунта для отслеживания"""
    if len(context.args) < 1:
        update.message.reply_text("❌ Пожалуйста, укажите имя пользователя Instagram\n"
                                "Пример: /add username")
        return

    user_id = str(update.effective_user.id)
    if not check_subscription(user_id):
        update.message.reply_text(
            "⚠️ Для добавления аккаунтов необходима подписка",
            reply_markup=get_subscription_keyboard()
        )
        return

    username = context.args[0].lower()

    try:
        # Проверяем существование аккаунта
        if username in user_subscriptions.get(user_id, []):
            update.message.reply_text(f"⚠️ Аккаунт @{username} уже отслеживается!")
            return

        # Отправляем начальное сообщение
        status_message = update.message.reply_text(f"🔄 Добавляю аккаунт @{username}...")
        
        # Быстрая проверка существования аккаунта
        try:
            user_id_inst = cl.user_id_from_username(username)
        except Exception as e:
            update.message.reply_text(f"❌ Ошибка: Не удалось найти аккаунт @{username}")
            return

        # Добавляем аккаунт в подписки
        if user_id not in user_subscriptions:
            user_subscriptions[user_id] = []
        user_subscriptions[user_id].append(username)
        save_user_data()
        
        status_message.edit_text(f"✅ Аккаунт @{username} успешно добавлен!\n🔄 Загружаю последние истории...")

        # Асинхронно загружаем истории
        def load_initial_stories():
            try:
                stories = get_stories(username)
                if stories:
                    # Сохраняем только ID историй без их загрузки
                    if user_id not in last_stories:
                        last_stories[user_id] = {}
                    last_stories[user_id][username] = set(str(story.pk) for story in stories)
                    save_user_data()
                    
                    status_message.edit_text(
                        f"✅ Аккаунт @{username} добавлен!\n"
                        f"📱 Найдено {len(stories)} историй\n"
                        "🔄 Новые истории будут приходить автоматически"
                    )
                else:
                    status_message.edit_text(
                        f"✅ Аккаунт @{username} добавлен!\n"
                        "ℹ️ Сейчас нет активных историй"
                    )
            except Exception as e:
                logger.error(f"Ошибка при загрузке историй: {str(e)}")
                status_message.edit_text(
                    f"✅ Аккаунт @{username} добавлен!\n"
                    "⚠️ Не удалось загрузить текущие истории\n"
                    "🔄 Новые истории будут приходить автоматически"
                )

        # Запускаем загрузку историй в отдельном потоке
        threading.Thread(target=load_initial_stories, daemon=True).start()

    except Exception as e:
        update.message.reply_text(f"❌ Ошибка при добавлении аккаунта @{username}")
        logger.error(f"Ошибка при добавлении аккаунта: {str(e)}")

def remove_account(update, context):
    """Удаление аккаунта из отслеживания"""
    if len(context.args) < 1:
        update.message.reply_text("❌ Пожалуйста, укажите имя пользователя Instagram\n"
                                "Пример: /remove username")
        return

    username = context.args[0].lower()
    user_id = str(update.effective_user.id)

    if username in user_subscriptions.get(user_id, []):
        user_subscriptions[user_id].remove(username)
        save_user_data()
        update.message.reply_text(f"✅ Аккаунт @{username} удален из отслеживания!")
    else:
        update.message.reply_text(f"⚠️ Аккаунт @{username} не найден в списке отслеживания!")

def list_subscriptions(update, context):
    """Показать список отслеживаемых аккаунтов"""
    user_id = str(update.effective_user.id)
    subscriptions = user_subscriptions.get(user_id, [])
    
    if not subscriptions:
        message = "📝 У вас нет отслеживаемых аккаунтов.\n\nИспользуйте /add username для добавления."
    else:
        message = "📋 *Ваши подписки:*\n\n"
        for i, username in enumerate(subscriptions, 1):
            message += f"{i}. @{username}\n"
        message += "\nДля удаления используйте /remove username"
    
    update.message.reply_text(message, parse_mode='Markdown')

def check_instagram_connection():
    """Проверка подключения к Instagram"""
    try:
        session.get("https://www.instagram.com", timeout=10)
        return True
    except Exception as e:
        logger.error(f"Ошибка подключения к Instagram: {str(e)}")
        return False

def process_user_stories(user_id, username, context):
    """Обработка историй для одного пользователя"""
    try:
        stories = get_stories(username)
        if stories:
            logger.info(f"Найдено {len(stories)} историй для {username}")
            
            # Получаем ID всех текущих историй
            current_story_ids = set(str(story.pk) for story in stories)
            
            # Инициализируем структуру для пользователя если её нет
            if user_id not in last_stories:
                last_stories[user_id] = {}
            if username not in last_stories[user_id]:
                last_stories[user_id][username] = set()
            
            # Получаем ID уже отправленных историй
            sent_story_ids = set(last_stories[user_id][username])
            
            # Находим новые истории
            new_story_ids = current_story_ids - sent_story_ids
            
            if new_story_ids:
                logger.info(f"Найдены новые истории для {username}: {new_story_ids}")
                
                # Создаем временную директорию для сохранения медиафайлов
                temp_dir = f"temp_{user_id}_{username}"
                os.makedirs(temp_dir, exist_ok=True)
                
                try:
                    # Отправляем каждую новую историю
                    for story in stories:
                        story_id = str(story.pk)
                        if story_id in new_story_ids:
                            try:
                                # Скачиваем историю
                                download_and_send_story(story, username, user_id, temp_dir, context)
                                
                            except Exception as e:
                                logger.error(f"Ошибка при отправке истории {story_id}: {str(e)}")
                                continue
                            
                finally:
                    # Очищаем временную директорию
                    if os.path.exists(temp_dir):
                        try:
                            os.rmdir(temp_dir)
                        except:
                            # Если директория не пуста, очищаем её содержимое
                            for file in os.listdir(temp_dir):
                                try:
                                    os.remove(os.path.join(temp_dir, file))
                                except:
                                    pass
                            try:
                                os.rmdir(temp_dir)
                            except:
                                pass
                            
    except Exception as e:
        logger.error(f"Ошибка при получении историй: {str(e)}")

def worker():
    """Рабочий поток для обработки задач"""
    while True:
        task = task_queue.get()
        if task is None:
            break
        try:
            task()
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи: {str(e)}")
        finally:
            task_queue.task_done()

def monitor_queue():
    """Мониторинг очереди задач"""
    while True:
        size = task_queue.qsize()
        if size > 0:
            logger.info(f"Размер очереди: {size}")
        time.sleep(60)  # Проверяем каждую минуту

def check_new_content(context):
    """Проверка нового контента"""
    try:
        logger.info("Начало проверки нового контента")
        
        # Проверяем авторизацию перед проверкой контента
        if not check_and_refresh_auth():
            logger.error("Не удалось авторизоваться в Instagram")
            return
            
        for user_id in user_subscriptions:
            if not check_subscription(user_id):
                logger.info(f"Пропуск проверки для {user_id} - нет активной подписки")
                continue
                
            for username in user_subscriptions[user_id]:
                try:
                    # Проверяем существование аккаунта
                    user_info = cl.user_info_by_username(username)
                    if not user_info:
                        logger.error(f"Не удалось получить информацию о пользователе {username}")
                        continue
                        
                    stories = cl.user_stories(user_info.pk)
                    
                    if stories:
                        logger.info(f"Найдено {len(stories)} историй у {username}")
                        # Проверяем, есть ли новые истории
                        if user_id not in last_stories:
                            last_stories[user_id] = {}
                        if username not in last_stories[user_id]:
                            last_stories[user_id][username] = {}
                            
                        for story in stories:
                            story_id = str(story.pk)
                            if story_id not in last_stories[user_id][username]:
                                # Сохраняем историю
                                last_stories[user_id][username][story_id] = {
                                    'timestamp': datetime.now().timestamp(),
                                    'sent': False
                                }
                                # Отправляем историю
                                try:
                                    download_and_send_story(story, username, user_id, f"temp_{user_id}_{username}", context)
                                    last_stories[user_id][username][story_id]['sent'] = True
                                except Exception as e:
                                    logger.error(f"Ошибка при отправке истории: {str(e)}")
                                
                except Exception as e:
                    logger.error(f"Ошибка при проверке {username}: {str(e)}")
                    continue
                    
        save_user_data()  # Сохраняем обновленные данные
        logger.info("Завершение проверки нового контента")
        
    except Exception as e:
        logger.error(f"Ошибка при проверке нового контента: {str(e)}")

def send_post_notification(context, user_id, username, post):
    """Отправка уведомления о новом посте"""
    message = (
        f"🔔 *Новый пост от @{username}!*\n\n"
        f"📝 Описание: {post.caption[:100]}...\n"
        f"❤️ Лайков: {post.likes}\n"
        f"💬 Комментариев: {post.comments}"
    )
    
    try:
        context.bot.send_message(chat_id=user_id, text=message, parse_mode='Markdown')
        send_media(context, user_id, username, post)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {str(e)}")

def send_story_notification(context, user_id, username, story_data):
    """Отправка уведомления о новой истории"""
    try:
        message = (
            f"📱 *Новая история от @{username}*\n"
            f"⏰ Время публикации: {story_data['date'].strftime('%H:%M:%S')}\n"
            f"📍 Тип: {'Видео' if story_data['is_video'] else 'Фото'}"
        )
        
        # Сначала отправляем медиафайл
        if os.path.exists(story_data['path']):
            try:
                if story_data['is_video']:
                    with open(story_data['path'], 'rb') as video:
                        context.bot.send_video(
                            chat_id=user_id, 
                            video=video,
                            caption=message,
                            parse_mode='Markdown'
                        )
                else:
                    with open(story_data['path'], 'rb') as photo:
                        context.bot.send_photo(
                            chat_id=user_id, 
                            photo=photo,
                            caption=message,
                            parse_mode='Markdown'
                        )
            except Exception as media_error:
                logger.error(f"Ошибка отправки медиафайла: {str(media_error)}")
                # Если не удалось отправить файл, отправляем текст и ссылку
                context.bot.send_message(
                    chat_id=user_id,
                    text=message + f"\n\n🔗 Ссылка на историю: {story_data['url']}",
                    parse_mode='Markdown'
                )
        else:
            # Если файл не существует, отправляем только текст и ссылку
            context.bot.send_message(
                chat_id=user_id,
                text=message + f"\n\n🔗 Ссылка на историю: {story_data['url']}",
                parse_mode='Markdown'
            )
                    
        # Удаляем временный файл
        try:
            if os.path.exists(story_data['path']):
                os.remove(story_data['path'])
            if os.path.exists(os.path.dirname(story_data['path'])):
                os.rmdir(os.path.dirname(story_data['path']))
        except Exception as cleanup_error:
            logger.error(f"Ошибка при очистке временных файлов: {str(cleanup_error)}")
            
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {str(e)}")

def send_media(context, user_id, username, item, is_story=False):
    """Отправка медиафайла"""
    temp_dir = f"temp_{username}"
    try:
        if is_story:
            cl.story_download(item.pk, target=temp_dir)
        else:
            cl.photo_download(item.pk, target=temp_dir)

        if item.is_video:
            video_path = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')][0]
            context.bot.send_video(chat_id=user_id, 
                                 video=open(f"{temp_dir}/{video_path}", 'rb'))
        else:
            photo_path = [f for f in os.listdir(temp_dir) if f.endswith('.jpg')][0]
            context.bot.send_photo(chat_id=user_id, 
                                 photo=open(f"{temp_dir}/{photo_path}", 'rb'))
    finally:
        # Очистка временных файлов
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                os.remove(f"{temp_dir}/{file}")
            os.rmdir(temp_dir)

def resolve_instagram_domain():
    """Получение IP адреса Instagram"""
    try:
        return socket.gethostbyname('i.instagram.com')
    except:
        return None

def cleanup_old_stories():
    """Очистка старых историй"""
    log_bot_action("Начало очистки старых историй")
    try:
        current_time = time.time()
        with data_lock:
            for user_id in list(last_stories.keys()):
                for username in list(last_stories[user_id].keys()):
                    # Очищаем истории старше 24 часов
                    last_stories[user_id][username] = set()
                    save_user_data()
        log_bot_action("Завершение очистки старых историй")
    except Exception as e:
        logger.error(f"Ошибка при очистке старых историй: {str(e)}")

def load_all_current_stories(update, context):
    """Загрузка всех текущих историй для пользователя"""
    if isinstance(update, CallbackQuery):
        user_id = str(update.from_user.id)
        status_message = update.edit_message_text("🔄 Загружаю текущие истории...")
    else:
        user_id = str(update.effective_user.id)
        status_message = update.message.reply_text("🔄 Загружаю текущие истории...")
    
    log_user_action(user_id, "Запросил загрузку историй")
    
    if not check_subscription(user_id):
        if isinstance(update, CallbackQuery):
            update.edit_message_text(
                "⚠️ Для загрузки историй необходима подписка",
                reply_markup=get_subscription_keyboard()
            )
        else:
            update.message.reply_text(
                "⚠️ Для загрузки историй необходима подписка",
                reply_markup=get_subscription_keyboard()
            )
        return

    total_stories = 0
    errors = []
    
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for username in user_subscriptions.get(user_id, []):
                try:
                    log_bot_action("Проверка историй", f"аккаунт: {username}")
                    user_id_instagram = cl.user_id_from_username(username)
                    stories = cl.user_stories(user_id_instagram)
                    
                    if not stories:
                        log_bot_action("Нет активных историй", f"аккаунт: {username}")
                        continue
                        
                    log_bot_action("Найдены истории", f"аккаунт: {username}, количество: {len(stories)}")
                    temp_dir = f"temp_{user_id}_{username}"
                    os.makedirs(temp_dir, exist_ok=True)

                    # Параллельная обработка историй
                    futures = []
                    for story in stories:
                        future = executor.submit(
                            download_and_send_story,
                            story,
                            username,
                            user_id,
                            temp_dir,
                            context
                        )
                        futures.append(future)

                    # Собираем результаты
                    for future in futures:
                        if future.result():
                            total_stories += 1
                            
                except Exception as e:
                    logger.error(f"Ошибка при обработке пользователя {username}: {str(e)}")
                    errors.append(f"Ошибка при получении историй от {username}")
                finally:
                    # Очищаем временную директорию
                    if os.path.exists(temp_dir):
                        try:
                            for file in os.listdir(temp_dir):
                                os.remove(os.path.join(temp_dir, file))
                            os.rmdir(temp_dir)
                        except Exception as e:
                            logger.error(f"Ошибка при очистке директории {temp_dir}: {str(e)}")

        # Изменяем отправку итоговых сообщений, добавляя кнопку возврата
        try:
            if total_stories > 0:
                message = f"✅ Загружено {total_stories} историй!"
                if errors:
                    message += "\n\n⚠️ Были ошибки:\n" + "\n".join(errors)
                status_message.edit_text(message, reply_markup=get_back_to_menu_keyboard())
            else:
                if errors:
                    status_message.edit_text(
                        "❌ Произошли ошибки при загрузке историй:\n" + "\n".join(errors),
                        reply_markup=get_back_to_menu_keyboard()
                    )
                else:
                    status_message.edit_text(
                        "ℹ️ Нет активных историй",
                        reply_markup=get_back_to_menu_keyboard()
                    )
        except Exception as e:
            logger.error(f"Критическая ошибка: {str(e)}")
            status_message.edit_text(
                "❌ Произошла критическая ошибка при загрузке историй",
                reply_markup=get_back_to_menu_keyboard()
            )
                
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        status_message.edit_text("❌ Произошла критическая ошибка при загрузке историй")

def send_invoice(update, context, plan):
    """Отправка счета на оплату через Telegram Stars"""
    try:
        plan_data = SUBSCRIPTION_PRICES[plan]
        
        # Получаем правильный chat_id
        chat_id = update.message.chat_id if hasattr(update, 'message') else update.callback_query.message.chat_id
        
        context.bot.send_invoice(
            chat_id=chat_id,
            title=plan_data['title'],
            description=plan_data['description'],
            payload=f"sub_{plan}",
            provider_token="",  # Для Stars оставляем пустым
            currency="XTR",    # Используем XTR для Stars
            prices=[LabeledPrice("Stars", plan_data['price'])],  # Цена в Stars (без умножения на 100)
            start_parameter=f"sub_{plan}",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        log_bot_action("Отправка счета Stars", f"user_id: {chat_id}, plan: {plan}")
    except Exception as e:
        logger.error(f"Ошибка отправки счета Stars: {str(e)}")
        error_text = "❌ Произошла ошибка при создании счета"
        if hasattr(update, 'message'):
            update.message.reply_text(error_text)
        else:
            update.callback_query.message.reply_text(error_text)

def button_handler(update, context):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    log_user_action(user_id, "Нажал кнопку", f"действие: {query.data}")

    try:
        if query.data == 'back_to_menu':
            log_bot_action("Возврат в меню", f"user_id: {user_id}")
            message = (
                "👋 Добро пожаловать в Instagram Monitor Bot!\n\n"
                "🔍 Я буду следить за выбранными вами Instagram аккаунтами и сообщать о новых:\n"
                "📸 Постах\n"
                "🎥 Историях\n\n"
                "Выберите действие:"
            )
            query.edit_message_text(text=message, reply_markup=get_main_menu_keyboard())
            query.answer()
        elif query.data == 'subscription_info':
            log_bot_action("Просмотр информации о подписке", f"user_id: {user_id}")
            show_subscription_info(query, context)
        elif query.data == 'load_stories':
            load_all_current_stories(query, context)
        elif query.data == 'add_account':
            query.edit_message_text(
                text="Чтобы добавить аккаунт для отслеживания, используйте команду:\n"
                     "/add username",
                reply_markup=get_back_to_menu_keyboard()
            )
        elif query.data == 'list_subscriptions':
            user_id = str(query.from_user.id)
            subscriptions = user_subscriptions.get(user_id, [])
            
            if not subscriptions:
                message = "📝 У вас нет отслеживаемых аккаунтов."
            else:
                message = "📋 *Ваши подписки:*\n\n"
                for i, username in enumerate(subscriptions, 1):
                    message += f"{i}. @{username}\n"
            
            query.edit_message_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=get_back_to_menu_keyboard()
            )
        elif query.data == 'help':
            query.edit_message_text(
                text="📚 *Помощь по командам:*\n\n"
                     "/start - Запустить бота\n"
                     "/add username - Добавить аккаунт\n"
                     "/remove username - Удалить аккаунт\n"
                     "/list - Показать подписки\n"
                     "/help - Показать помощь",
                parse_mode='Markdown',
                reply_markup=get_back_to_menu_keyboard()
            )
        elif query.data.startswith('sub_'):
            plan = query.data.replace('sub_', '')
            if plan in SUBSCRIPTION_PRICES:
                try:
                    send_invoice(query, context, plan)
                except Exception as e:
                    logger.error(f"Ошибка создания платежа: {str(e)}")
                    query.answer("❌ Ошибка при создании платежа")
                return
        
        query.answer()
    except Exception as e:
        logger.error(f"Ошибка в обработчике кнопок: {str(e)}")
        try:
            query.answer("Произошла ошибка. Попробуйте позже.")
        except:
            pass

def pre_checkout_handler(update, context):
    """Предварительная проверка платежа"""
    try:
        query = update.pre_checkout_query
        # Проверяем, что все в порядке
        if query.invoice_payload.startswith('sub_'):
            plan = query.invoice_payload.replace('sub_', '')
            if plan in SUBSCRIPTION_PRICES:
                query.answer(ok=True)
                log_bot_action("Подтверждение платежа", f"user_id: {query.from_user.id}, plan: {plan}")
                return
        query.answer(ok=False, error_message="Неверный план подписки")
    except Exception as e:
        logger.error(f"Ошибка предварительной проверки: {str(e)}")
        if query:
            query.answer(ok=False, error_message="Произошла ошибка при проверке платежа")

def successful_payment_callback(update, context):
    """Обработка успешного платежа"""
    try:
        payment = update.message.successful_payment
        user_id = str(update.effective_user.id)
        plan = payment.invoice_payload.replace('sub_', '')
        
        if plan not in SUBSCRIPTION_PRICES:
            logger.error(f"Неверный план подписки: {plan}")
            update.message.reply_text("❌ Ошибка активации подписки: неверный план")
            return

        days = {'1month': 30, '3months': 90, '6months': 180, '1year': 365}
        expires = datetime.now() + timedelta(days=days[plan])
        
        # Сохраняем данные о подписке
        with data_lock:
            if user_id not in user_subscriptions_data:
                user_subscriptions_data[user_id] = {}
            user_subscriptions_data[user_id].update({
                'expires': expires.timestamp(),
                'plan': plan,
                'payment_id': payment.telegram_payment_charge_id
            })
            save_subscription_data()
        
        message = (
            f"✅ Подписка успешно оформлена!\n\n"
            f"📅 Тариф: {SUBSCRIPTION_PRICES[plan]['title']}\n"
            f"⏳ Срок действия: до {expires.strftime('%d.%m.%Y')}"
        )
        update.message.reply_text(message, reply_markup=get_main_menu_keyboard())
        log_bot_action("Оформлена подписка", f"user_id: {user_id}, plan: {plan}")
        
    except Exception as e:
        logger.error(f"Ошибка при активации подписки: {str(e)}")
        update.message.reply_text("❌ Произошла ошибка при активации подписки")

def initialize_files():
    """Инициализация всех необходимых файлов"""
    try:
        # Инициализация user_data.json
        if not os.path.exists('user_data.json'):
            with open('user_data.json', 'w') as f:
                json.dump({
                    'subscriptions': {},
                    'posts': {},
                    'stories': {}
                }, f)
            logger.info("Создан файл user_data.json")

        # Инициализация subscriptions.json
        if not os.path.exists('subscriptions.json'):
            with open('subscriptions.json', 'w') as f:
                json.dump({}, f)
            logger.info("Создан файл subscriptions.json")

        # Инициализация users.txt
        if not os.path.exists('users.txt'):
            with open('users.txt', 'w') as f:
                f.write('')
            logger.info("Создан файл users.txt")

    except Exception as e:
        logger.error(f"Ошибка при инициализации файлов: {str(e)}")

def check_and_refresh_auth():
    """Проверка и обновление авторизации в Instagram"""
    try:
        if not cl.user_id or not cl.sessionid:
            logger.info("Требуется повторная авторизация в Instagram")
            return auth_instagram()
        
        # Проверяем валидность сессии через приватный API
        try:
            cl.get_timeline_feed()  # Используем более надежный метод проверки
            return True
        except Exception as e:
            if 'login_required' in str(e):
                logger.error("Сессия истекла, требуется повторная авторизация")
                if os.path.exists('session.json'):
                    os.remove('session.json')
                return auth_instagram()
            logger.error(f"Ошибка проверки сессии: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при проверке авторизации: {str(e)}")
        return False

def auth_instagram(update=None, context=None):
    """Авторизация в Instagram"""
    try:
        status_message = None
        if update:
            status_message = update.message.reply_text("🔄 Выполняю авторизацию в Instagram...")

        # Сначала удаляем старую сессию
        if os.path.exists('session.json'):
            os.remove('session.json')
            
        # Устанавливаем настройки клиента
        cl.set_device({
            "app_version": "269.0.0.18.75",
            "android_version": "28",
            "android_release": "9.0",
            "dpi": "480dpi",
            "resolution": "1080x2034",
            "manufacturer": "OnePlus",
            "device": "ONEPLUS A6013",
            "model": "OnePlus 6T",
            "cpu": "qcom",
            "version_code": "314665256"
        })
        
        # Пробуем авторизоваться
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        cl.dump_settings('session.json')
        
        # Проверяем подключение
        cl.get_timeline_feed()
        
        message = "✅ Успешно авторизовались в Instagram"
        logger.info(message)
        if status_message:
            status_message.edit_text(message, reply_markup=get_back_to_menu_keyboard())
        return True

    except Exception as e:
        error_message = f"❌ Ошибка авторизации в Instagram: {str(e)}"
        logger.error(error_message)
        if os.path.exists('session.json'):
            os.remove('session.json')
        if status_message:
            status_message.edit_text(error_message, reply_markup=get_back_to_menu_keyboard())
        return False

def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")
    try:
        # Запускаем веб-сервер для keep-alive
        keep_alive()
        logger.info("Keep-alive сервер запущен")
        
        # Инициализируем файлы и загружаем данные
        initialize_files()
        load_user_data()
        load_subscription_data()
        logger.info("Файлы и данные инициализированы")

        # Авторизуемся в Instagram при запуске
        logger.info("Подключение к Instagram...")
        if not check_and_refresh_auth():
            logger.error("Не удалось подключиться к Instagram. Завершение работы.")
            return
        logger.info("Успешно подключились к Instagram")

        updater = Updater(TELEGRAM_TOKEN, use_context=True)
        dp = updater.dispatcher
        
        # Добавляем обработчики команд
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("add", add_account))
        dp.add_handler(CommandHandler("remove", remove_account))
        dp.add_handler(CommandHandler("list", list_subscriptions))
        dp.add_handler(CommandHandler("loadstories", load_all_current_stories))
        dp.add_handler(CallbackQueryHandler(button_handler))

        # Запускаем проверку каждые 10 минут
        updater.job_queue.run_repeating(check_new_content, interval=600, first=10)
        updater.job_queue.run_repeating(lambda ctx: cleanup_old_stories(), interval=7200, first=7200)

        logger.info("Бот запущен и готов к работе")
        updater.start_polling(timeout=30, drop_pending_updates=True)
        updater.idle()
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {str(e)}")
        raise

if __name__ == '__main__':
    keep_alive()
    main()
