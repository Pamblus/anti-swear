import json
import re
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import ChatPermissions

# --- Константы и Инициализация (Без изменений) ---

# Загрузка матерных слов из файла
def load_bad_words():
    # Файл 'bad_words.txt' должен существовать в директории
    try:
        with open('bad_words.txt', 'r', encoding='utf-8') as f:
            return [line.strip().lower() for line in f if line.strip()]
    except FileNotFoundError:
        print("⚠️ Файл 'bad_words.txt' не найден. Бот будет использовать пустой список матов.")
        return []

# Белый список слов (не считать матом)
WHITE_LIST = [
    "жопа", "говно", "говнецо", "писька", "член", "пенис", "сосал", "сосать", "ссать", "ссаки", "сиськи",
    "попа", "задница", "срака", "бляха", "блин", "еперный", "ёперный", "ёпрст", "епрст",
    "хер", "хрен", "хрень", "херовый", "хреновый", "мудак", "мудило", "мудозвон",
    "шалава", "трахать", "трах", "секс", "сиськи", "сисек", "сисечки"
]

# Загрузка извинений
def load_apologies():
    return [
        "извините", "извиняюсь", "прости", "простите", "прошу прощения",
        "сорян", "сорри", "виноват", "виновата", "пардон",
        "pardon", "sorry", "my bad", "mea culpa", "приношу извинения",
        "извиняюсь", "извинение", "прошу простить", "виновен", "не хотел обидеть"
    ]

# Инициализация констант
bad_words = load_bad_words()
apologies = load_apologies()
bad_words_filtered = [word for word in bad_words if word not in WHITE_LIST]

# --- Глобальный Менеджер для Данных Чатов и Пользователей ---

# Новый класс для хранения данных
class GlobalManager:
    def __init__(self, filename='bot_data.json'):
        self.filename = filename
        self.data = self.load_data()
    
    # Структура данных:
    # {
    #     "chat_id": {
    #         "enabled": True/False,
    #         "users": {
    #             "user_id": {
    #                 'id': ...,
    #                 'username': ...,
    #                 ... (как в оригинальном user_manager)
    #             },
    #             ...
    #         }
    #     },
    #     ...
    # }

    def load_data(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                # Десериализация дат (опционально, но полезно)
                data = json.load(f)
                return data
        return {}

    def save_data(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # --- Работа с Чатами (ChatManager функционал) ---

    def _get_chat(self, chat_id):
        chat_id_str = str(chat_id)
        if chat_id_str not in self.data:
            self.data[chat_id_str] = {
                'enabled': True,
                'users': {}
            }
            self.save_data()
        return self.data[chat_id_str]

    def is_bot_enabled(self, chat_id):
        return self.data.get(str(chat_id), {}).get('enabled', True)

    def enable_bot(self, chat_id):
        self._get_chat(chat_id)['enabled'] = True
        self.save_data()

    def disable_bot(self, chat_id):
        self._get_chat(chat_id)['enabled'] = False
        self.save_data()
        
    def get_all_chats(self):
        return self.data.items() # Возвращает (chat_id_str, chat_data)

    # --- Работа с Пользователями (UserManager функционал) ---

    def _get_users_db(self, chat_id):
        return self._get_chat(chat_id)['users']

    def get_user(self, chat_id, user_id, update: Update):
        users_db = self._get_users_db(chat_id)
        user_id_str = str(user_id)
        
        if user_id_str not in users_db:
            user = update.effective_user
            users_db[user_id_str] = {
                'id': user_id,
                'username': user.username or '',
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'reputation': 100,
                'swear_count': 0,
                'created_at': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'muted_until': None,
                'swear_timer': None
            }
            self.save_data()
        else:
            users_db[user_id_str]['last_seen'] = datetime.now().isoformat()
        
        return users_db[user_id_str]

    def update_user(self, chat_id, user_id, data):
        users_db = self._get_users_db(chat_id)
        user_id_str = str(user_id)
        
        if user_id_str in users_db:
            users_db[user_id_str].update(data)
            # Ограничиваем репутацию максимум 100
            if 'reputation' in data and users_db[user_id_str]['reputation'] > 100:
                users_db[user_id_str]['reputation'] = 100
            self.save_data()

    def add_swear_timer(self, chat_id, user_id):
        self.update_user(chat_id, user_id, {'swear_timer': datetime.now().isoformat()})

    def clear_swear_timer(self, chat_id, user_id):
        self.update_user(chat_id, user_id, {'swear_timer': None})

    def mute_user(self, chat_id, user_id, hours=1):
        mute_until = datetime.now() + timedelta(hours=hours)
        self.update_user(chat_id, user_id, {'muted_until': mute_until.isoformat()})
        return mute_until

    def is_muted(self, chat_id, user_id):
        users_db = self._get_users_db(chat_id)
        user = users_db.get(str(user_id))
        
        if not user or not user.get('muted_until'):
            return False
            
        mute_until = datetime.fromisoformat(user['muted_until'])
        return datetime.now() < mute_until

# Инициализация нового менеджера
global_manager = GlobalManager()

# --- Команды ---

# Декоратор для проверки, что команда запущена в группе и бот включен
def group_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type not in [
            'group', 'supergroup'
        ]:
            # В личных сообщениях не работаем
            # В оригинальном коде нет текста для лички, поэтому просто return
            return
        
        # Проверка на выключение бота
        if not global_manager.is_bot_enabled(update.effective_chat.id) and func.__name__ not in ['enable_bot_command']:
             # Если бот выключен, обрабатываем только команду включения
            return

        return await func(update, context)
    return wrapper

@group_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот-антимат. Не матерись! 🥰\n/helpm - список команд")

@group_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📋 *Доступные команды:*

/profilem - твой профиль (репутация, маты)
/topm - топ по репутации
/topmm - топ по матам
/onm - включить бота в этом чате
/offm - выключить бота в этом чате
/helpm - эта справка

📝 *Правила:*
- Мат = -1 к репутации за КАЖДОЕ матерное слово
- Извинение на моё сообщение = +1 к репутации (макс. 100)
- Если не извинился за 5 минут = мут на 1 час
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

@group_only
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = global_manager.get_user(chat_id, update.effective_user.id, update)
    
    # Проверяем таймер мута
    mute_info = ""
    if user.get('muted_until'):
        mute_until = datetime.fromisoformat(user['muted_until'])
        if datetime.now() < mute_until:
            time_left = mute_until - datetime.now()
            # Проверка, чтобы избежать ошибки деления на 0, если время < 1 мин
            minutes = int(time_left.total_seconds() // 60)
            if minutes > 0:
                mute_info = f"🔇 В муте: {minutes} мин.\n"
            else:
                 mute_info = "🔇 В муте: <1 мин.\n"
                 
    # Проверяем таймер извинения
    timer_info = ""
    if user.get('swear_timer'):
        swear_time = datetime.fromisoformat(user['swear_timer'])
        time_passed = datetime.now() - swear_time
        minutes_passed = time_passed.total_seconds() / 60
        if minutes_passed < 5:
            time_left = 5 - minutes_passed
            timer_info = f"⏰ Извинись через: {int(time_left)} мин.\n"
            
    profile_text = f"""
📊 *Твой профиль*

👤 Имя: {user['first_name']} {user.get('last_name', '')}
🔖 @{user['username'] if user['username'] else 'нет'}
🆔 ID: `{user['id']}`
⭐ Репутация: *{user['reputation']}*
💢 Матов: *{user['swear_count']}*
{mute_info}{timer_info}
📅 Создан: {user['created_at'][:10]}
"""
    await update.message.reply_text(profile_text, parse_mode='Markdown')

@group_only
async def top_reputation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Получаем пользователей только для текущего чата
    users_list = list(global_manager._get_users_db(chat_id).values())
    sorted_users = sorted(users_list, key=lambda x: x['reputation'], reverse=True)[:10]
    
    if not sorted_users:
        await update.message.reply_text("Пока нет данных.")
        return
        
    text = "🏆 *Топ по репутации:*\n\n"
    for i, user in enumerate(sorted_users, 1):
        name = user['first_name'] or user['username'] or f"User {user['id']}"
        text += f"{i}. {name}: *{user['reputation']}* ⭐\n"
        
    await update.message.reply_text(text, parse_mode='Markdown')

@group_only
async def top_swear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Получаем пользователей только для текущего чата
    users_list = list(global_manager._get_users_db(chat_id).values())
    sorted_users = sorted(users_list, key=lambda x: x['swear_count'], reverse=True)[:10]
    
    if not sorted_users:
        await update.message.reply_text("Пока нет данных.")
        return
        
    text = "💢 *Топ по матам:*\n\n"
    for i, user in enumerate(sorted_users, 1):
        name = user['first_name'] or user['username'] or f"User {user['id']}"
        text += f"{i}. {name}: *{user['swear_count']}* 😈\n"
        
    await update.message.reply_text(text, parse_mode='Markdown')

@group_only
async def enable_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Эта команда работает, даже если бот был 'выключен' в БД, чтобы его можно было включить
    global_manager.enable_bot(update.effective_chat.id)
    await update.message.reply_text("✅ Бот включен в этом чате!")

@group_only
async def disable_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global_manager.disable_bot(update.effective_chat.id)
    await update.message.reply_text("❌ Бот отключен в этом чате.")

# --- Обработка Сообщений ---

# Проверка на извинение (Без изменений)
def check_apology(text):
    text_lower = text.lower()
    for apology in apologies:
        if text_lower.startswith(apology):
            # Проверяем, что после извинения есть хотя бы 2 слова
            rest = text_lower[len(apology):].strip()
            # Проверяем, что после извинения есть хотя бы 2 символа, если не 2 слова
            if len(rest.split()) >= 2 or len(rest) >= 2:
                return True
    return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Фильтр на работу ТОЛЬКО в группах
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Проверяем, включен ли бот в чате
    if not global_manager.is_bot_enabled(chat_id):
        return
        
    user = global_manager.get_user(chat_id, user_id, update)
    text = update.message.text
    
    # Сообщения без текста игнорируем
    if not text:
        return
        
    # Проверка на мут
    if global_manager.is_muted(chat_id, user_id):
        try:
            # Удаляем сообщение, если пользователь в муте
            await update.message.delete()
        except Exception:
            # Бот должен быть админом с правом удалять сообщения
            pass
        # Сообщаем о муте
        await update.message.reply_text(f"@{update.effective_user.username or update.effective_user.first_name} ты в муте на 1 час!")
        return
        
    text_lower = text.lower()
    
    # Проверка на извинение (ответ на сообщение бота)
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        if check_apology(text):
            # Очищаем таймер извинения
            global_manager.clear_swear_timer(chat_id, user_id)
            
            # Даем +1 репутации, но не больше 100
            new_rep = min(user['reputation'] + 1, 100)
            global_manager.update_user(chat_id, user_id, {
                'reputation': new_rep
            })
            await update.message.reply_text(f"Принято! +1 к репутации. Твой рейтинг: {new_rep} ⭐")
            return
            
    # Проверка на мат
    found_bad_words = []
    for bad_word in bad_words_filtered:
        # Использование \b для точного совпадения слова
        pattern = r'\b' + re.escape(bad_word) + r'\b'
        matches = re.findall(pattern, text_lower)
        for match in matches:
            found_bad_words.append(match)
            
    if found_bad_words:
        # Удаляем дубликаты для подсчета УНИКАЛЬНЫХ матов
        unique_bad_words = list(set(found_bad_words))
        swear_count = len(unique_bad_words)
        
        # Устанавливаем таймер извинения, если еще не установлен
        if not user.get('swear_timer'):
            global_manager.add_swear_timer(chat_id, user_id)
            
        # Обновляем статистику
        new_reputation = max(user['reputation'] - swear_count, 0)
        global_manager.update_user(chat_id, user_id, {
            'reputation': new_reputation,
            'swear_count': user['swear_count'] + swear_count
        })
        
        words_list = ", ".join(f"'{w}'" for w in unique_bad_words[:3])
        if len(unique_bad_words) > 3:
            words_list += f" и ещё {len(unique_bad_words) - 3}"
            
        # Базовый текст сообщения
        message_text = (
            f"не матерись мой хороший 🥰\n"
            f"Найдено матов: {swear_count} ({words_list})\n"
            f"минус -{swear_count} репка, твой рейтинг: {new_reputation}\n"
            f"⏰ У тебя 5 минут чтобы извиниться!"
        )
        
        # Если 2 или более матов, отправляем картинку вместе с текстом
        if swear_count >= 2:
            try:
                # Проверяем, существует ли файл mat.jpg
                if os.path.exists('mat.jpg'):
                    with open('mat.jpg', 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=message_text
                        )
                else:
                    # Если файла нет, отправляем только текст
                    await update.message.reply_text(f"⚠️ Файл mat.jpg не найден!\n{message_text}")
            except Exception as e:
                # Если ошибка при отправке фото, отправляем только текст
                # print(f"Ошибка при отправке фото: {e}") # Для отладки
                await update.message.reply_text(f"⚠️ Ошибка при отправке фото: {str(e)}\n{message_text}")
        else:
            # Если менее 2 матов, отправляем только текст
            await update.message.reply_text(message_text)

# --- Фоновая Задача ---

async def mute_user_telegram_api(context: ContextTypes.DEFAULT_TYPE, chat_id, user_id, mute_until):
    """Фактически мутирует пользователя в Telegram."""
    try:
        # Превращаем метку времени в UNIX-таймстамп (обязательно для restrict_chat_member)
        until_date = int(mute_until.timestamp())
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            # Ограничиваем только отправку сообщений
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date # Срок мута
        )
        return True
    except Exception as e:
        # print(f"Не удалось замутить пользователя {user_id} в чате {chat_id}: {e}") # Для отладки
        # Если бот не является админом или не имеет нужных прав, мут не сработает
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Не удалось замутить пользователя ID {user_id}. Убедитесь, что бот является администратором с правом 'Ограничивать пользователей'."
        )
        return False

# Фоновая задача для проверки таймеров
async def check_timers(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    # Итерируем по всем чатам
    for chat_id_str, chat_data in global_manager.get_all_chats():
        chat_id = int(chat_id_str)
        users = chat_data.get('users', {})
        
        for user_id_str, user in users.items():
            user_id = int(user_id_str)
            
            # 1. Проверяем таймер извинения
            if user.get('swear_timer'):
                swear_time = datetime.fromisoformat(user['swear_timer'])
                time_passed = now - swear_time
                
                if time_passed.total_seconds() >= 300: # 5 минут
                    # Мут на 1 час в БД
                    mute_until_dt = global_manager.mute_user(chat_id, user_id, 1)
                    
                    # Фактический мут в Telegram
                    success = await mute_user_telegram_api(context, chat_id, user_id, mute_until_dt)
                    
                    # Очищаем таймер в БД (только если удалось замутить или если мы не хотим повторять попытку)
                    if success:
                         global_manager.clear_swear_timer(chat_id, user_id)
                         await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Пользователь ID {user_id} не извинился за 5 минут и получил мут на 1 час! 🔇"
                        )
                    # Если мут не удался, таймер сбросится, но пользователь не будет замучен фактически.
                    # Для простоты и соответствия логике "один раз - 5 минут" сбросим таймер.
                    else:
                         global_manager.clear_swear_timer(chat_id, user_id)


# --- Главная Функция ---

def main():
    # Получи токен у @BotFather
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    # Создаем приложение
    app = Application.builder().token(TOKEN).build()
    
    # Обработчики команд. Используем group_only фильтр в декораторе
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("helpm", help_command))
    app.add_handler(CommandHandler("profilem", profile_command))
    app.add_handler(CommandHandler("topm", top_reputation_command))
    app.add_handler(CommandHandler("topmm", top_swear_command))
    app.add_handler(CommandHandler("onm", enable_bot_command))
    app.add_handler(CommandHandler("offm", disable_bot_command))
    
    # Обработчик сообщений. Добавляем фильтр, чтобы не обрабатывать личку, хотя это уже есть в handle_message
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_message))
    
    # Добавляем фоновую задачу для проверки таймеров (каждую минуту)
    job_queue = app.job_queue
    if job_queue:
        # Запускаем через 10 секунд после старта, затем повторяем каждую минуту
        job_queue.run_repeating(check_timers, interval=60, first=10)
        
    print("🤖 Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()