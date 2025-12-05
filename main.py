import json
import re
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка матерных слов из файла
def load_bad_words():
    with open('bad_words.txt', 'r', encoding='utf-8') as f:
        return [line.strip().lower() for line in f if line.strip()]

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

# Работа с пользователями
class UserManager:
    def __init__(self, filename='users.json'):
        self.filename = filename
        self.users = self.load_users()
        self.swear_timers = {}  # {user_id: {"time": datetime, "count": int}}
    
    def load_users(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_users(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=2)
    
    def get_user(self, user_id, update: Update):
        if str(user_id) not in self.users:
            user = update.effective_user
            self.users[str(user_id)] = {
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
            self.save_users()
        else:
            self.users[str(user_id)]['last_seen'] = datetime.now().isoformat()
        return self.users[str(user_id)]
    
    def update_user(self, user_id, data):
        if str(user_id) in self.users:
            self.users[str(user_id)].update(data)
            # Ограничиваем репутацию максимум 100
            if 'reputation' in data and self.users[str(user_id)]['reputation'] > 100:
                self.users[str(user_id)]['reputation'] = 100
            self.save_users()
    
    def add_swear_timer(self, user_id):
        self.users[str(user_id)]['swear_timer'] = datetime.now().isoformat()
        self.save_users()
    
    def clear_swear_timer(self, user_id):
        self.users[str(user_id)]['swear_timer'] = None
        self.save_users()
    
    def mute_user(self, user_id, hours=1):
        mute_until = datetime.now() + timedelta(hours=hours)
        self.users[str(user_id)]['muted_until'] = mute_until.isoformat()
        self.save_users()
        return mute_until
    
    def is_muted(self, user_id):
        user = self.users.get(str(user_id))
        if not user or not user.get('muted_until'):
            return False
        
        mute_until = datetime.fromisoformat(user['muted_until'])
        return datetime.now() < mute_until

# Работа с чатами
class ChatManager:
    def __init__(self, filename='chats.json'):
        self.filename = filename
        self.chats = self.load_chats()
    
    def load_chats(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_chats(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.chats, f, ensure_ascii=False, indent=2)
    
    def is_bot_enabled(self, chat_id):
        return self.chats.get(str(chat_id), True)
    
    def enable_bot(self, chat_id):
        self.chats[str(chat_id)] = True
        self.save_chats()
    
    def disable_bot(self, chat_id):
        self.chats[str(chat_id)] = False
        self.save_chats()

# Инициализация
bad_words = load_bad_words()
apologies = load_apologies()
user_manager = UserManager()
chat_manager = ChatManager()

# Фильтруем матерные слова, убирая белый список
bad_words_filtered = [word for word in bad_words if word not in WHITE_LIST]

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот-антимат. Не матерись! 🥰\n/helpm - список команд")

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

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = user_manager.get_user(update.effective_user.id, update)
    
    # Проверяем таймер мута
    mute_info = ""
    if user.get('muted_until'):
        mute_until = datetime.fromisoformat(user['muted_until'])
        if datetime.now() < mute_until:
            time_left = mute_until - datetime.now()
            mute_info = f"🔇 В муте: {int(time_left.total_seconds() // 60)} мин.\n"
    
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

async def top_reputation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users_list = list(user_manager.users.values())
    sorted_users = sorted(users_list, key=lambda x: x['reputation'], reverse=True)[:10]
    
    if not sorted_users:
        await update.message.reply_text("Пока нет данных.")
        return
    
    text = "🏆 *Топ по репутации:*\n\n"
    for i, user in enumerate(sorted_users, 1):
        name = user['first_name'] or user['username'] or f"User {user['id']}"
        text += f"{i}. {name}: *{user['reputation']}* ⭐\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def top_swear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users_list = list(user_manager.users.values())
    sorted_users = sorted(users_list, key=lambda x: x['swear_count'], reverse=True)[:10]
    
    if not sorted_users:
        await update.message.reply_text("Пока нет данных.")
        return
    
    text = "💢 *Топ по матам:*\n\n"
    for i, user in enumerate(sorted_users, 1):
        name = user['first_name'] or user['username'] or f"User {user['id']}"
        text += f"{i}. {name}: *{user['swear_count']}* 😈\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def enable_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_manager.enable_bot(update.effective_chat.id)
    await update.message.reply_text("✅ Бот включен в этом чате!")

async def disable_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_manager.disable_bot(update.effective_chat.id)
    await update.message.reply_text("❌ Бот отключен в этом чате.")

# Проверка на извинение
def check_apology(text):
    text_lower = text.lower()
    for apology in apologies:
        if text_lower.startswith(apology):
            # Проверяем, что после извинения есть хотя бы 2 слова
            rest = text_lower[len(apology):].strip()
            if len(rest.split()) >= 2:
                return True
    return False

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, включен ли бот в чате
    if not chat_manager.is_bot_enabled(update.effective_chat.id):
        return
    
    user = user_manager.get_user(update.effective_user.id, update)
    text = update.message.text
    
    # Проверка на мут
    if user_manager.is_muted(update.effective_user.id):
        await update.message.delete()
        await update.message.reply_text(f"@{update.effective_user.username or update.effective_user.first_name} ты в муте на 1 час!")
        return
    
    text_lower = text.lower()
    
    # Проверка на извинение (ответ на сообщение бота)
    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        if check_apology(text):
            # Очищаем таймер извинения
            user_manager.clear_swear_timer(update.effective_user.id)
            
            # Даем +1 репутации, но не больше 100
            new_rep = min(user['reputation'] + 1, 100)
            user_manager.update_user(user['id'], {
                'reputation': new_rep
            })
            await update.message.reply_text(f"Принято! +1 к репутации. Твой рейтинг: {new_rep} ⭐")
            return
    
    # Проверка на мат
    found_bad_words = []
    for bad_word in bad_words_filtered:
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
            user_manager.add_swear_timer(update.effective_user.id)
        
        # Обновляем статистику
        new_reputation = max(user['reputation'] - swear_count, 0)
        user_manager.update_user(user['id'], {
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
                await update.message.reply_text(f"⚠️ Ошибка при отправке фото: {str(e)}\n{message_text}")
        else:
            # Если менее 2 матов, отправляем только текст
            await update.message.reply_text(message_text)

# Фоновая задача для проверки таймеров
async def check_timers(context: ContextTypes.DEFAULT_TYPE):
    for user_id_str, user in user_manager.users.items():
        # Проверяем таймер извинения
        if user.get('swear_timer'):
            swear_time = datetime.fromisoformat(user['swear_timer'])
            time_passed = datetime.now() - swear_time
            
            if time_passed.total_seconds() >= 300:  # 5 минут
                # Мут на 1 час
                mute_until = user_manager.mute_user(int(user_id_str), 1)
                
                # Очищаем таймер
                user_manager.clear_swear_timer(int(user_id_str))
                
                # Уведомляем в чате (в реальном боте нужно знать chat_id)
                # Для этого нужно хранить информацию о чатах пользователей
                pass

def main():
    # Получи токен у @BotFather
    TOKEN = "ВАШ_TELEGRAM_BOT_TOKEN"
    
    # Создаем приложение
    app = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("helpm", help_command))
    app.add_handler(CommandHandler("profilem", profile_command))
    app.add_handler(CommandHandler("topm", top_reputation_command))
    app.add_handler(CommandHandler("topmm", top_swear_command))
    app.add_handler(CommandHandler("onm", enable_bot_command))
    app.add_handler(CommandHandler("offm", disable_bot_command))
    
    # Обработчик сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Добавляем фоновую задачу для проверки таймеров (каждую минуту)
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_timers, interval=60, first=10)
    
    print("🤖 Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
