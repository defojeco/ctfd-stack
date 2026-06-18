CTFd._internal.challenge.data = undefined;
CTFd._internal.challenge.renderer = null;
CTFd._internal.challenge.preRender = function () {};
CTFd._internal.challenge.render    = null;

// Глобальный флаг инициализации (защита от повторов)
window.mcInitialized = false;

CTFd._internal.challenge.postRender = function () {
  // Alpine рендерит асинхронно через nextTick, поэтому DOM может быть ещё не готов.
  // Пробуем сразу, потом через requestAnimationFrame, потом через таймер.
  mcTryBind();
  requestAnimationFrame(mcTryBind);
  setTimeout(mcTryBind, 50);
  setTimeout(mcTryBind, 200);
};

function mcTryBind() {
  // Проверяем, какой формат используется
  var singleContainer = document.getElementById('mc-options-list');
  var multipleQuestions = document.querySelectorAll('.mc-question-block');

  if (multipleQuestions.length > 0) {
    // Новый формат: множественные вопросы
    mcBindMultipleQuestions(multipleQuestions);
  } else if (singleContainer) {
    // Старый формат: один вопрос
    mcBindSingleQuestion(singleContainer);
  }
}

function mcBindSingleQuestion(container) {
  if (!container) return;
  if (container.getAttribute('data-mc-bound') === '1') return;

  container.setAttribute('data-mc-bound', '1');

  // Делегированный обработчик клика на весь контейнер
  container.addEventListener('click', function (e) {
    var label = e.target.closest('.mc-option');
    if (!label) return;

    var input = label.querySelector('input[type=radio], input[type=checkbox]');
    if (!input) return;

    // Если кликнули прямо на input — браузер сам переключит, только обновим UI
    if (e.target === input) {
      setTimeout(mcUpdateSelectionSingle, 0);
      return;
    }

    // Клик по label/тексту — переключаем вручную
    e.preventDefault();
    e.stopPropagation();

    if (input.type === 'radio') {
      // Снять выделение у всех radio в группе
      container.querySelectorAll('input[type=radio]').forEach(function (r) {
        r.checked = false;
      });
      input.checked = true;
    } else {
      input.checked = !input.checked;
    }

    mcUpdateSelectionSingle();
  });

  // Обработка изменений через клавиатуру (Space/Enter)
  container.addEventListener('change', function(e) {
    if (e.target.matches('input[type=radio], input[type=checkbox]')) {
      mcUpdateSelectionSingle();
    }
  });
}

function mcUpdateSelectionSingle() {
  var inputs = document.querySelectorAll('#mc-options-list input[type=radio], #mc-options-list input[type=checkbox]');
  var chosen = [];

  inputs.forEach(function (inp) {
    var label = inp.closest('.mc-option');
    if (!label) return;

    if (inp.checked) {
      label.classList.add('selected');
      chosen.push(inp.value);
    } else {
      label.classList.remove('selected');
    }
  });

  var hiddenInput = document.getElementById('challenge-input');
  if (hiddenInput) {
    hiddenInput.value = chosen.join(',');
    hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
    hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function mcBindMultipleQuestions(questionBlocks) {
  if (questionBlocks.length === 0) return;

  questionBlocks.forEach(function(block) {
    var alreadyBound = block.getAttribute('data-mc-bound') === '1';
    if (alreadyBound) return;

    block.setAttribute('data-mc-bound', '1');
    var qIdx = block.getAttribute('data-q-idx');
    var optionsContainer = block.querySelector('.mc-options');

    if (!optionsContainer) return;

    // Делегированный обработчик для каждого блока вопроса
    optionsContainer.addEventListener('click', function(e) {
      var label = e.target.closest('.mc-option');
      if (!label) return;

      var input = label.querySelector('input[type=radio], input[type=checkbox]');
      if (!input) return;

      // Если кликнули прямо на input — браузер сам переключит
      if (e.target === input) {
        setTimeout(mcUpdateSelectionMultiple, 0);
        return;
      }

      // Клик по label/тексту — переключаем вручную
      e.preventDefault();
      e.stopPropagation();

      if (input.type === 'radio') {
        // Снять выделение у всех radio в этом вопросе
        optionsContainer.querySelectorAll('input[type=radio]').forEach(function (r) {
          r.checked = false;
        });
        input.checked = true;
      } else {
        input.checked = !input.checked;
      }

      mcUpdateSelectionMultiple();
    });

    // Обработка изменений через клавиатуру
    optionsContainer.addEventListener('change', function(e) {
      if (e.target.matches('input[type=radio], input[type=checkbox]')) {
        mcUpdateSelectionMultiple();
      }
    });
  });
}

function mcUpdateSelectionMultiple() {
  var questionBlocks = document.querySelectorAll('.mc-question-block');
  var answers = [];

  questionBlocks.forEach(function(block) {
    var qIdx = block.getAttribute('data-q-idx');
    var inputs = block.querySelectorAll('input[type=radio], input[type=checkbox]');
    var chosen = [];

    inputs.forEach(function(inp) {
      var label = inp.closest('.mc-option');
      if (!label) return;

      if (inp.checked) {
        label.classList.add('selected');
        chosen.push(inp.value);
      } else {
        label.classList.remove('selected');
      }
    });

    if (chosen.length > 0) {
      answers.push('q' + qIdx + ':' + chosen.join(','));
    }
  });

  var hiddenInput = document.getElementById('challenge-input');
  if (hiddenInput) {
    hiddenInput.value = answers.join('|');
    hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
    hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

CTFd._internal.challenge.submit = function (preview) {
  var challenge_id = parseInt(CTFd.lib.$('#challenge-id').val());
  var submission   = CTFd.lib.$('#challenge-input').val();

  if (!submission || submission.trim() === '') {
    var list = document.getElementById('mc-options-list') || document.querySelector('.mc-question-block');
    if (list) {
      list.style.animation = 'none';
      void list.offsetHeight;
      list.style.animation = 'mc-shake .4s ease';
    }
  }

  var body   = { challenge_id: challenge_id, submission: submission };
  var params = {};
  if (preview) params['preview'] = true;

  return CTFd.api.post_challenge_attempt(params, body).then(function (response) {
    if (response.status === 429 || response.status === 403) return response;

    var correct = response.data && response.data.status === 'correct';
    var selected = document.querySelectorAll('.mc-option.selected');
    selected.forEach(function (el) {
      el.classList.add(correct ? 'feedback-correct' : 'feedback-wrong');
      setTimeout(function () {
        el.classList.remove('feedback-correct', 'feedback-wrong');
      }, 1800);
    });

    if (correct) {
      document.querySelectorAll('.mc-option input').forEach(function (inp) {
        inp.disabled = true;
      });
      document.querySelectorAll('.mc-option').forEach(function (lbl) {
        lbl.style.cursor = 'default';
      });
    }

    return response;
  });
};

// Анимация тряски
(function () {
  if (!document.getElementById('mc-anim-style')) {
    var s = document.createElement('style');
    s.id = 'mc-anim-style';
    s.textContent = '@keyframes mc-shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}';
    document.head.appendChild(s);
  }
})();
