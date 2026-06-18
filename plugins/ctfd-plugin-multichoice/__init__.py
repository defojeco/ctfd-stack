"""
CTFd MultiChoice Plugin v2.0
Функции:
  - Несколько правильных ответов (все должны быть отмечены)
  - Режим одиночного ответа (radio)
  - Перемешивание вариантов ответа
  - Частичный зачёт (за каждый правильный вариант)
  - Русский интерфейс
  - Красивый UI с карточками вместо чекбоксов
"""

import json
from flask import Blueprint
from CTFd.models import (
    db, Solves, Fails, Flags, Challenges,
    ChallengeFiles, Tags, Hints, Awards,
)
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.migrations import upgrade
from CTFd.utils.user import get_current_user, get_ip
from CTFd.utils.modes import get_model


def _as_bool(value, default=False):
    """Привести значение к bool. CTFd serializeJSON присылает чекбоксы как
    настоящие JSON-булевы (True/False), а form-data — как строки."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "on", "yes")


# --- Локализация плагина -----------------------------------------------------
MC_STRINGS = {
    "en": {
        "create_title": "Multiple choice challenge",
        "create_desc": "The participant selects one or more options from the list. Add options below and mark the correct ones.",
        "update_intro": "Editing a multiple choice challenge. Correct options are highlighted in green.",
        "options_label": "Answer options",
        "options_help": "Add options and mark ✓ the correct ones. At least 2 options.",
        "add_option": "+ Add option",
        "add_question": "+ Add question",
        "question_label": "Question",
        "question_placeholder": "Enter question text...",
        "mode_label": "Selection mode",
        "mode_single": "One correct answer",
        "mode_multi": "Several correct answers",
        "mode_help": "Defines the control type: radio or checkbox",
        "value_label": "Points",
        "settings_label": "Options",
        "shuffle": "Shuffle options",
        "partial": "Partial scoring",
        "partial_mode_label": "Partial scoring mode",
        "partial_mode_percentage": "Percentage-based",
        "partial_mode_fixed": "Fixed points per question",
        "partial_settings_label": "Partial scoring settings",
        "points_per_question": "Points per correct question",
        "correct_tag": "✓ Correct",
        "option_placeholder": "Enter an answer option...",
        "remove": "Remove",
        "remove_question": "Remove question",
        "min_two": "At least 2 options required",
        "need_option": "Add at least one answer option",
        "need_correct": "Mark at least one correct option",
        "select_one": "Select one option",
        "select_all": "Select all correct options",
        "msg_correct": "Correct!",
        "msg_correct_all": "Correct! All options selected properly.",
        "msg_partial": "Partial credit: {score} points ({percent}% correct)",
        "msg_wrong": "Incorrect. Try again.",
        "msg_almost": "Almost! {n} more correct option(s) to select.",
        "msg_has_wrong": "There are incorrect options in your answer.",
        "msg_not_configured": "Challenge is not configured (no answer options)",
        "msg_no_correct": "Challenge is not configured (no correct options)",
    },
    "ru": {
        "create_title": "Задание с выбором ответа",
        "create_desc": "Участник выбирает один или несколько вариантов из списка. Добавьте варианты ниже и отметьте правильные.",
        "update_intro": "Редактирование задания с выбором ответа. Правильные варианты отмечены зелёным.",
        "options_label": "Варианты ответа",
        "options_help": "Добавьте варианты и отметьте ✓ правильные. Минимум 2 варианта.",
        "add_option": "+ Добавить вариант",
        "add_question": "+ Добавить вопрос",
        "question_label": "Вопрос",
        "question_placeholder": "Введите текст вопроса...",
        "mode_label": "Режим выбора",
        "mode_single": "Один правильный ответ",
        "mode_multi": "Несколько правильных",
        "mode_help": "Определяет тип элемента: radio или checkbox",
        "value_label": "Очки за задание",
        "settings_label": "Опции",
        "shuffle": "Перемешивать варианты",
        "partial": "Частичный зачёт",
        "partial_mode_label": "Режим частичного зачёта",
        "partial_mode_percentage": "Процентный",
        "partial_mode_fixed": "Фиксированные баллы за вопрос",
        "partial_settings_label": "Настройки частичного зачёта",
        "points_per_question": "Баллов за правильный вопрос",
        "correct_tag": "✓ Правильный",
        "option_placeholder": "Введите вариант ответа...",
        "remove": "Удалить",
        "remove_question": "Удалить вопрос",
        "min_two": "Минимум 2 варианта",
        "need_option": "Добавьте хотя бы один вариант ответа",
        "need_correct": "Отметьте хотя бы один правильный вариант",
        "select_one": "Выберите один вариант",
        "select_all": "Выберите все правильные варианты",
        "msg_correct": "Правильно!",
        "msg_correct_all": "Правильно! Все варианты выбраны верно.",
        "msg_partial": "Частичный зачёт: {score} баллов ({percent}% правильных)",
        "msg_wrong": "Неверно. Попробуйте ещё раз.",
        "msg_almost": "Почти! Не выбрано ещё {n} правильных вариантов.",
        "msg_has_wrong": "Есть неверные варианты в ответе.",
        "msg_not_configured": "Задача не настроена (нет вариантов ответа)",
        "msg_no_correct": "Задача не настроена (нет правильных вариантов)",
    },
    "es": {
        "create_title": "Desafío de opción múltiple",
        "create_desc": "El participante selecciona una o más opciones de la lista. Agregue opciones a continuación y marque las correctas.",
        "update_intro": "Editando un desafío de opción múltiple. Las opciones correctas están resaltadas en verde.",
        "options_label": "Opciones de respuesta",
        "options_help": "Agregue opciones y marque ✓ las correctas. Al menos 2 opciones.",
        "add_option": "+ Agregar opción",
        "add_question": "+ Agregar pregunta",
        "question_label": "Pregunta",
        "question_placeholder": "Ingrese el texto de la pregunta...",
        "mode_label": "Modo de selección",
        "mode_single": "Una respuesta correcta",
        "mode_multi": "Varias respuestas correctas",
        "mode_help": "Define el tipo de control: radio o checkbox",
        "value_label": "Puntos",
        "settings_label": "Opciones",
        "shuffle": "Mezclar opciones",
        "partial": "Puntuación parcial",
        "partial_mode_label": "Modo de puntuación parcial",
        "partial_mode_percentage": "Basado en porcentaje",
        "partial_mode_fixed": "Puntos fijos por pregunta",
        "partial_settings_label": "Configuración de puntuación parcial",
        "points_per_question": "Puntos por pregunta correcta",
        "correct_tag": "✓ Correcto",
        "option_placeholder": "Ingrese una opción de respuesta...",
        "remove": "Eliminar",
        "remove_question": "Eliminar pregunta",
        "min_two": "Se requieren al menos 2 opciones",
        "need_option": "Agregue al menos una opción de respuesta",
        "need_correct": "Marque al menos una opción correcta",
        "select_one": "Seleccione una opción",
        "select_all": "Seleccione todas las opciones correctas",
        "msg_correct": "¡Correcto!",
        "msg_correct_all": "¡Correcto! Todas las opciones seleccionadas correctamente.",
        "msg_partial": "Crédito parcial: {score} puntos ({percent}% correcto)",
        "msg_wrong": "Incorrecto. Inténtalo de nuevo.",
        "msg_almost": "¡Casi! Faltan {n} opciones correctas por seleccionar.",
        "msg_has_wrong": "Hay opciones incorrectas en tu respuesta.",
        "msg_not_configured": "El desafío no está configurado (sin opciones de respuesta)",
        "msg_no_correct": "El desafío no está configurado (sin opciones correctas)",
    },
}


def _mc_lang():
    """Двухбуквенный код текущего языка CTFd ('ru'/'en'); по умолчанию 'en'."""
    try:
        from CTFd.utils.user import get_locale
        locale = get_locale() or "en"
    except Exception:
        locale = "en"
    # Нормализуем locale: zh_CN → zh, pt_BR → pt, en-US → en
    lang = str(locale).replace("_", "-").split("-")[0].lower()
    return lang if lang in MC_STRINGS else "en"


def mc_trans(key):
    """Перевод строки плагина под текущую локаль CTFd (для шаблонов Jinja)."""
    lang = _mc_lang()
    table = MC_STRINGS.get(lang, MC_STRINGS["en"])
    return table.get(key) or MC_STRINGS["en"].get(key, key)


class MultiChoiceChallenge(Challenges):
    __mapper_args__ = {"polymorphic_identity": "multichoice"}

    id = db.Column(db.Integer, db.ForeignKey("challenges.id"), primary_key=True)

    # Варианты ответа, разделённые символом §
    # Формат каждого варианта: текст|0 (неправильный) или текст|1 (правильный)
    # Пример: "Вариант А|0§Вариант Б|1§Вариант В|0§Вариант Г|1"
    #
    # НОВЫЙ ФОРМАТ (множественные вопросы):
    # Вопросы разделяются символом ¶
    # Формат: "текст_вопроса_1¶вариант1|0§вариант2|1¶¶текст_вопроса_2¶вариант1|1§вариант2|0"
    # Структура: вопрос¶варианты¶¶следующий_вопрос¶варианты
    flagchoose = db.Column(db.Text, default="")

    # Режим: "multi" — несколько правильных, "single" — один правильный
    mode = db.Column(db.String(16), default="single")

    # Перемешивать варианты при показе
    shuffle = db.Column(db.Boolean, default=True)

    # Частичный зачёт: давать очки за каждый правильный вариант
    partial_score = db.Column(db.Boolean, default=False)

    # Режим частичного зачёта: "percentage" (процентный) или "fixed" (фиксированные баллы за вопрос)
    partial_mode = db.Column(db.String(16), default="percentage", nullable=True)

    # Настройки частичного зачёта в формате JSON
    # Для percentage: {"90": 100, "70": 80, "50": 60, "0": 40}
    # Для fixed: {"points_per_question": 20}
    partial_settings = db.Column(db.Text, default="", nullable=True)


class MultiChoiceValueChallenge(BaseChallenge):
    id = "multichoice"
    name = "multichoice"

    templates = {
        "create": "/plugins/ctfd-plugin-multichoice/assets/create.html",
        "update": "/plugins/ctfd-plugin-multichoice/assets/update.html",
        "view":   "/plugins/ctfd-plugin-multichoice/assets/view.html",
    }
    scripts = {
        "create": "/plugins/ctfd-plugin-multichoice/assets/create.js",
        "update": "/plugins/ctfd-plugin-multichoice/assets/update.js",
        "view":   "/plugins/ctfd-plugin-multichoice/assets/view.js",
    }
    route = "/plugins/ctfd-plugin-multichoice/assets/"
    blueprint = Blueprint(
        "multichoice", __name__,
        template_folder="templates",
        static_folder="assets",
    )
    challenge_model = MultiChoiceChallenge

    @classmethod
    def read(cls, challenge):
        challenge = MultiChoiceChallenge.query.filter_by(id=challenge.id).first()

        # Парсим flagchoose для определения формата
        flagchoose_raw = challenge.flagchoose or ""
        questions_data = []

        if "¶" in flagchoose_raw:
            # Новый формат: множественные вопросы
            questions_raw = flagchoose_raw.split("¶¶")
            for q_raw in questions_raw:
                q_raw = q_raw.strip()
                if not q_raw:
                    continue
                parts = q_raw.split("¶", 1)
                if len(parts) == 2:
                    questions_data.append({
                        "text": parts[0].strip(),
                        "options": parts[1].strip()
                    })

        data = {
            "id":             challenge.id,
            "name":           challenge.name,
            "value":          challenge.value,
            "description":    challenge.description,
            "flagchoose":     flagchoose_raw,
            "questions":      questions_data,  # Добавляем распарсенные вопросы
            "mode":           challenge.mode or "single",
            "shuffle":        challenge.shuffle if challenge.shuffle is not None else True,
            "partial_score":  challenge.partial_score or False,
            "partial_mode":   challenge.partial_mode or "percentage",
            "partial_settings": challenge.partial_settings or "",
            "connection_info": challenge.connection_info,
            "category":       challenge.category,
            "state":          challenge.state,
            "max_attempts":   challenge.max_attempts,
            "type":           challenge.type,
            "type_data": {
                "id":        cls.id,
                "name":      cls.name,
                "templates": cls.templates,
                "scripts":   cls.scripts,
            },
        }
        return data

    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()

        challenge.name        = data.get("name", challenge.name)
        challenge.description = data.get("description", challenge.description)
        challenge.value       = int(data.get("value", challenge.value))
        challenge.max_attempts = int(data.get("max_attempts", challenge.max_attempts or 0))
        challenge.category    = data.get("category", challenge.category)
        challenge.state       = data.get("state", challenge.state)

        # Собираем варианты из формы
        # Фронт присылает flagchoose как строку "текст|0§текст|1§..."
        flagchoose = data.get("flagchoose", challenge.flagchoose or "")
        challenge.flagchoose  = flagchoose
        challenge.mode        = data.get("mode", challenge.mode or "single")
        challenge.shuffle     = _as_bool(data.get("shuffle"), True)
        challenge.partial_score = _as_bool(data.get("partial_score"), False)
        challenge.partial_mode = data.get("partial_mode", challenge.partial_mode or "percentage")
        challenge.partial_settings = data.get("partial_settings", challenge.partial_settings or "")

        db.session.commit()
        return challenge

    @classmethod
    def create(cls, request):
        data = request.form or request.get_json()
        challenge = MultiChoiceChallenge(
            name         = data.get("name", ""),
            description  = data.get("description", ""),
            value        = int(data.get("value", 0)),
            max_attempts = int(data.get("max_attempts", 0)),
            category     = data.get("category", ""),
            type         = "multichoice",
            state        = data.get("state", "visible"),
            flagchoose   = data.get("flagchoose", ""),
            mode         = data.get("mode", "single"),
            shuffle      = _as_bool(data.get("shuffle"), True),
            partial_score = _as_bool(data.get("partial_score"), False),
            partial_mode = data.get("partial_mode", "percentage"),
            partial_settings = data.get("partial_settings", ""),
        )
        db.session.add(challenge)
        db.session.commit()
        return challenge

    @classmethod
    def attempt(cls, challenge, request):
        """
        Проверка ответа участника.
        Возвращает (bool, str) — (правильно?, сообщение)
        """
        data = request.form or request.get_json()
        submission = data.get("submission", "").strip()
        t = lambda k: mc_trans(k)

        # Парсим варианты задачи
        raw_options = (challenge.flagchoose or "").strip()
        if not raw_options:
            return False, t("msg_not_configured")

        # Проверяем, используется ли новый формат (множественные вопросы)
        # Новый формат: вопрос¶варианты¶¶следующий_вопрос¶варианты
        if "¶" in raw_options:
            result = cls._attempt_multiple_questions(challenge, submission, raw_options, t)
            # Сохраняем информацию о частичных баллах во временный атрибут challenge
            if result[0] and "Частичный зачёт" in result[1]:
                # Извлекаем количество баллов из сообщения
                import re
                match = re.search(r'(\d+)\s+баллов', result[1])
                if match:
                    # Сохраняем в challenge как временный атрибут
                    challenge._partial_score = int(match.group(1))
                else:
                    challenge._partial_score = None
            else:
                challenge._partial_score = None
            return result
        else:
            challenge._partial_score = None
            return cls._attempt_single_question(challenge, submission, raw_options, t)

    @classmethod
    def _attempt_single_question(cls, challenge, submission, raw_options, t):
        """Проверка ответа для старого формата (один вопрос)"""
        options = []
        for opt in raw_options.split("§"):
            opt = opt.strip()
            if not opt:
                continue
            if "|" in opt:
                text, correct = opt.rsplit("|", 1)
                options.append((text.strip(), correct.strip() == "1"))
            else:
                options.append((opt, False))

        correct_texts = {text for text, is_correct in options if is_correct}

        if not correct_texts:
            return False, t("msg_no_correct")

        # Ответ участника — список выбранных вариантов, разделённых запятой
        chosen = {s.strip() for s in submission.split(",") if s.strip()}

        if challenge.mode == "single":
            # Одиночный выбор: должен выбрать ровно один правильный
            if len(correct_texts) == 1 and chosen == correct_texts:
                return True, t("msg_correct")
            else:
                return False, t("msg_wrong")
        else:
            # Мультивыбор: все правильные выбраны, ни одного лишнего
            if chosen == correct_texts:
                return True, t("msg_correct_all")
            elif chosen & correct_texts and not (chosen - correct_texts):
                # Часть правильных выбрана, лишних нет
                missing = len(correct_texts) - len(chosen & correct_texts)
                return False, t("msg_almost").format(n=missing)
            elif chosen - correct_texts:
                return False, t("msg_has_wrong")
            else:
                return False, t("msg_wrong")

    @classmethod
    def _attempt_multiple_questions(cls, challenge, submission, raw_options, t):
        """Проверка ответа для нового формата (множественные вопросы)"""
        # Парсим вопросы: разделитель между вопросами — ¶¶
        questions_raw = raw_options.split("¶¶")
        questions = []

        for q_raw in questions_raw:
            q_raw = q_raw.strip()
            if not q_raw:
                continue

            # Разделяем текст вопроса и варианты: вопрос¶варианты
            parts = q_raw.split("¶", 1)
            if len(parts) != 2:
                continue

            question_text = parts[0].strip()
            options_raw = parts[1].strip()

            # Парсим варианты для этого вопроса
            options = []
            for opt in options_raw.split("§"):
                opt = opt.strip()
                if not opt:
                    continue
                if "|" in opt:
                    text, correct = opt.rsplit("|", 1)
                    options.append((text.strip(), correct.strip() == "1"))
                else:
                    options.append((opt, False))

            if options:
                questions.append({
                    "text": question_text,
                    "options": options,
                    "correct": {text for text, is_correct in options if is_correct}
                })

        if not questions:
            return False, t("msg_not_configured")

        # Проверяем, что у всех вопросов есть правильные ответы
        for q in questions:
            if not q["correct"]:
                return False, t("msg_no_correct")

        # Парсим ответ участника
        # Формат: "q0:ответ1,ответ2|q1:ответ3|q2:ответ4,ответ5"
        # где q0, q1, q2 — индексы вопросов
        user_answers = {}
        if submission:
            for part in submission.split("|"):
                part = part.strip()
                if not part or ":" not in part:
                    continue
                q_idx_str, answers_str = part.split(":", 1)
                try:
                    q_idx = int(q_idx_str.replace("q", ""))
                    answers = {a.strip() for a in answers_str.split(",") if a.strip()}
                    user_answers[q_idx] = answers
                except (ValueError, AttributeError):
                    continue

        # Проверяем ответы на все вопросы
        correct_count = 0
        total_count = len(questions)

        for idx, question in enumerate(questions):
            user_ans = user_answers.get(idx, set())
            correct_ans = question["correct"]

            if challenge.mode == "single":
                # Для single mode: должен выбрать ровно один правильный
                if len(correct_ans) == 1 and user_ans == correct_ans:
                    correct_count += 1
            else:
                # Для multi mode: все правильные выбраны, лишних нет
                if user_ans == correct_ans:
                    correct_count += 1

        # Вычисляем процент правильных ответов
        percent = int((correct_count / total_count) * 100) if total_count > 0 else 0

        # Если все правильно
        if correct_count == total_count:
            return True, t("msg_correct_all")

        # Если включён частичный зачёт
        if challenge.partial_score:
            return cls._calculate_partial_score(challenge, correct_count, total_count, percent, t)

        # Без частичного зачёта — просто неверно
        return False, t("msg_wrong")

    @classmethod
    def _calculate_partial_score(cls, challenge, correct_count, total_count, percent, t):
        """Вычисление частичного зачёта"""
        partial_mode = challenge.partial_mode or "percentage"
        max_points = challenge.value

        if partial_mode == "fixed":
            # Фиксированные баллы за каждый правильный вопрос
            try:
                settings = json.loads(challenge.partial_settings or "{}")
                points_per_question = float(settings.get("points_per_question", 0))
                score = correct_count * points_per_question
            except (json.JSONDecodeError, ValueError):
                score = 0
        else:
            # Процентный режим (по умолчанию)
            # Дефолтные пороги: 90-100% → 100%, 70-89% → 80%, 50-69% → 60%, <50% → 40%
            try:
                settings = json.loads(challenge.partial_settings or "{}")
            except json.JSONDecodeError:
                settings = {}

            # Дефолтные значения
            if not settings:
                settings = {"90": 100, "70": 80, "50": 60, "0": 40}

            # Находим подходящий порог
            score_percent = 40  # По умолчанию
            thresholds = sorted([(int(k), v) for k, v in settings.items()], reverse=True)
            for threshold, reward in thresholds:
                if percent >= threshold:
                    score_percent = reward
                    break

            score = (max_points * score_percent) / 100

        # Округляем до целого
        score = int(score)

        if score > 0:
            # Возвращаем частичный зачёт как успех, но с особым сообщением
            # CTFd будет засчитывать это как solve, но с меньшими очками
            return True, t("msg_partial").format(score=score, percent=percent)
        else:
            return False, t("msg_wrong")

    @classmethod
    def solve(cls, user, team, challenge, request):
        """
        Начисление баллов при правильном ответе.
        Поддерживает частичный зачёт.
        """
        # Проверяем, есть ли частичные баллы (сохранённые в attempt)
        partial_score = getattr(challenge, '_partial_score', None)

        if partial_score is not None and partial_score < challenge.value:
            # Частичный зачёт - создаём solve и award с частичными баллами
            solve = Solves(
                user_id=user.id if user else None,
                team_id=team.id if team else None,
                challenge_id=challenge.id,
                ip=get_ip(req=request),
                provided=""
            )
            db.session.add(solve)

            # Создаём award с частичными баллами (разница между полными и частичными)
            # Задание даёт challenge.value баллов, но мы хотим дать только partial_score
            # Поэтому создаём отрицательный award на разницу
            award = Awards(
                user_id=user.id if user else None,
                team_id=team.id if team else None,
                name=f"{challenge.name} - корректировка",
                description=f"Частичное решение ({partial_score}/{challenge.value})",
                value=partial_score - challenge.value,  # Отрицательное значение для корректировки
                category=challenge.category
            )
            db.session.add(award)

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                raise e
        else:
            # Полный зачёт - используем стандартную логику
            super(MultiChoiceValueChallenge, cls).solve(user, team, challenge, request)

    @classmethod
    def fail(cls, user, team, challenge, request):
        super().fail(user, team, challenge, request)

    @staticmethod
    def delete(challenge):
        Fails.query.filter_by(challenge_id=challenge.id).delete()
        Solves.query.filter_by(challenge_id=challenge.id).delete()
        Flags.query.filter_by(challenge_id=challenge.id).delete()
        files = ChallengeFiles.query.filter_by(challenge_id=challenge.id).all()
        for f in files:
            try:
                from CTFd.utils.uploads import delete_file
                delete_file(f.id)
            except Exception:
                pass
        ChallengeFiles.query.filter_by(challenge_id=challenge.id).delete()
        Tags.query.filter_by(challenge_id=challenge.id).delete()
        Hints.query.filter_by(challenge_id=challenge.id).delete()
        MultiChoiceChallenge.query.filter_by(id=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()


def load(app):
    # ПАТЧ: Исправляем баг CTFd с китайским locale zh_CN → zh-CN
    # Это предотвращает ошибку "invalid language tag" в браузере
    try:
        # Работаем напрямую с таблицей config через SQL
        result = db.session.execute(
            db.text("UPDATE config SET value = REPLACE(value, '_', '-') WHERE key = 'default_locale' AND value LIKE '%\\_%'")
        )
        if result.rowcount > 0:
            db.session.commit()
            app.logger.info(f"[multichoice] Patched {result.rowcount} locale config(s)")
    except Exception as e:
        app.logger.warning(f"[multichoice] Could not patch locale: {e}")

    # Регистрируем тип задания
    CHALLENGE_CLASSES["multichoice"] = MultiChoiceValueChallenge

    # Проверяем и добавляем колонки ДО создания таблиц
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)

        # Если таблица существует, добавляем новые колонки
        if inspector.has_table('multichoice_challenge'):
            columns = [col['name'] for col in inspector.get_columns('multichoice_challenge')]

            # Добавляем partial_mode если его нет
            if 'partial_mode' not in columns:
                try:
                    db.session.execute(text(
                        "ALTER TABLE multichoice_challenge ADD COLUMN partial_mode VARCHAR(16)"
                    ))
                    db.session.execute(text(
                        "UPDATE multichoice_challenge SET partial_mode = 'percentage' WHERE partial_mode IS NULL"
                    ))
                    db.session.commit()
                    app.logger.info("[multichoice] Added partial_mode column")
                except Exception as e:
                    app.logger.warning(f"[multichoice] Could not add partial_mode: {e}")
                    db.session.rollback()

            # Добавляем partial_settings если его нет
            if 'partial_settings' not in columns:
                try:
                    db.session.execute(text(
                        "ALTER TABLE multichoice_challenge ADD COLUMN partial_settings TEXT"
                    ))
                    db.session.execute(text(
                        "UPDATE multichoice_challenge SET partial_settings = '' WHERE partial_settings IS NULL"
                    ))
                    db.session.commit()
                    app.logger.info("[multichoice] Added partial_settings column")
                except Exception as e:
                    app.logger.warning(f"[multichoice] Could not add partial_settings: {e}")
                    db.session.rollback()
    except Exception as e:
        app.logger.warning(f"[multichoice] Migration check failed: {e}")

    # Теперь создаём/обновляем таблицы
    try:
        app.db.create_all()
        app.logger.info("[multichoice] Tables created/verified")
    except Exception as e:
        app.logger.error(f"[multichoice] Error creating tables: {e}")

    # Делаем переводчик плагина доступным в шаблонах как mc_trans('key')
    app.jinja_env.globals.update(mc_trans=mc_trans)
    register_plugin_assets_directory(
        app, base_path="/plugins/ctfd-plugin-multichoice/assets/"
    )
