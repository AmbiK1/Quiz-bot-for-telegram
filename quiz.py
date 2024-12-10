import sqlite3
import asyncio
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import json

# Конфигурация
TOKEN = 'ваш_токен_бота'
ADMIN_ID = 'ваш_id_админа'  # ID администратора для редактирования вопросов

# Инициализация бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


# Состояния FSM
class QuizStates(StatesGroup):
    answering = State()
    adding_question = State()
    adding_answer = State()


# Работа с БД
def init_db():
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()

    # Создание таблицы вопросов
    c.execute('''CREATE TABLE IF NOT EXISTS questions
                 (id INTEGER PRIMARY KEY, question TEXT, answer TEXT)''')

    # Создание таблицы результатов
    c.execute('''CREATE TABLE IF NOT EXISTS results
                 (user_id INTEGER, username TEXT, correct_answers INTEGER, 
                  total_questions INTEGER, quiz_date TIMESTAMP)''')

    conn.commit()
    conn.close()


# Загрузка вопросов из БД
def get_questions():
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute('SELECT question, answer FROM questions')
    questions = c.fetchall()
    conn.close()
    return questions


# Сохранение результатов
def save_result(user_id, username, correct_answers, total_questions):
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute('''INSERT INTO results (user_id, username, correct_answers, 
                total_questions, quiz_date) VALUES (?, ?, ?, ?, ?)''',
              (user_id, username, correct_answers, total_questions, datetime.now()))
    conn.commit()
    conn.close()


# Команда начала викторины
@dp.message_handler(commands=['start_quiz'])
async def start_quiz(message: types.Message, state: FSMContext):
    questions = get_questions()
    if not questions:
        await message.answer("В базе нет вопросов. Администратор должен добавить их.")
        return

    # Перемешиваем вопросы
    random.shuffle(questions)

    async with state.proxy() as data:
        data['questions'] = questions
        data['current_question'] = 0
        data['correct_answers'] = 0

    await QuizStates.answering.set()
    await send_question(message, state)


async def send_question(message, state):
    async with state.proxy() as data:
        if data['current_question'] >= len(data['questions']):
            # Викторина закончена
            await finish_quiz(message, state)
            return

        question = data['questions'][data['current_question']][0]
        await message.answer(f"Вопрос {data['current_question'] + 1}:\n{question}")


async def finish_quiz(message, state):
    async with state.proxy() as data:
        correct = data['correct_answers']
        total = len(data['questions'])

    save_result(message.from_user.id, message.from_user.username, correct, total)

    await message.answer(
        f"Викторина завершена!\nПравильных ответов: {correct} из {total}"
    )
    await state.finish()


# Обработка ответов
@dp.message_handler(state=QuizStates.answering)
async def process_answer(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        correct_answer = data['questions'][data['current_question']][1].lower()
        if message.text.lower() == correct_answer:
            data['correct_answers'] += 1
            await message.answer("Правильно! ✅")
        else:
            await message.answer(f"Неправильно! Правильный ответ: {correct_answer}")

        data['current_question'] += 1
        await send_question(message, state)


# Команды администратора для управления вопросами
@dp.message_handler(commands=['add_question'], user_id=ADMIN_ID)
async def cmd_add_question(message: types.Message):
    await QuizStates.adding_question.set()
    await message.answer("Введите новый вопрос:")


@dp.message_handler(state=QuizStates.adding_question)
async def process_question(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['new_question'] = message.text

    await QuizStates.adding_answer.set()
    await message.answer("Теперь введите правильный ответ:")


@dp.message_handler(state=QuizStates.adding_answer)
async def process_answer_admin(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        question = data['new_question']

    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute('INSERT INTO questions (question, answer) VALUES (?, ?)',
              (question, message.text))
    conn.commit()
    conn.close()

    await message.answer("Вопрос успешно добавлен!")
    await state.finish()


# Просмотр статистики
@dp.message_handler(commands=['stats'])
async def show_stats(message: types.Message):
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute('''SELECT username, AVG(correct_answers*100.0/total_questions) as avg_score, 
                 COUNT(*) as attempts FROM results WHERE user_id = ? GROUP BY user_id''',
              (message.from_user.id,))
    stats = c.fetchone()
    conn.close()

    if stats:
        await message.answer(
            f"Ваша статистика:\n"
            f"Средний процент правильных ответов: {stats[1]:.1f}%\n"
            f"Количество попыток: {stats[2]}"
        )
    else:
        await message.answer("У вас пока нет результатов.")


# Экспорт вопросов
@dp.message_handler(commands=['export_questions'], user_id=ADMIN_ID)
async def export_questions(message: types.Message):
    questions = get_questions()
    questions_dict = [{"question": q[0], "answer": q[1]} for q in questions]

    with open('questions.json', 'w', encoding='utf-8') as f:
        json.dump(questions_dict, f, ensure_ascii=False, indent=2)

    await message.answer_document(open('questions.json', 'rb'))


if __name__ == '__main__':
    init_db()
    executor.start_polling(dp, skip_updates=True)