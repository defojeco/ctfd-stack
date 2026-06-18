// CTFd 3.8.5 сериализует форму через $(form).serializeJSON() и сам шлёт JSON
// на /api/v1/challenges. Скрытое поле name="flagchoose" попадает в payload
// автоматически — перехватывать fetch/XHR не нужно. Вся логика редактора
// вариантов находится в create.html (он вставляется в DOM после загрузки).

CTFd.plugin.run((_CTFd) => {
  const $ = _CTFd.lib.$;

  // Вызываем mcBuildField если он доступен (из create.html)
  if (typeof window.mcBuildField === 'function') {
    window.mcBuildField();
  }

  // ВАЖНО: После создания multichoice-задания CTFd показывает модальное окно
  // "Options" для добавления флагов. Для multichoice это не нужно — ответы
  // хранятся в поле flagchoose, а не в таблице Flags. Автоматически закрываем
  // это окно и перенаправляем на страницу редактирования задания.

  // Перехватываем успешный ответ от API создания задания
  const originalFetch = window.fetch;
  window.fetch = function(...args) {
    return originalFetch.apply(this, args).then(response => {
      // Клонируем response чтобы можно было прочитать body дважды
      const clonedResponse = response.clone();

      // Проверяем, это ли создание multichoice задания
      if (args[0] && args[0].includes('/api/v1/challenges') &&
          args[1] && args[1].method === 'POST') {

        clonedResponse.json().then(data => {
          if (data.success && data.data && data.data.type === 'multichoice') {
            console.log('[MC] Multichoice challenge created:', data.data.id);

            // Закрываем модальное окно флагов через небольшую задержку
            setTimeout(function() {
              // Ищем и закрываем любые модальные окна связанные с флагами
              const modals = $('.modal:visible, [id*="flag-modal"], [id*="options-modal"]');
              modals.each(function() {
                $(this).modal('hide');
              });

              // Перенаправляем на страницу редактирования
              window.location.href = CTFd.config.urlRoot + '/admin/challenges/' + data.data.id;
            }, 200);
          }
        }).catch(() => {});
      }

      return response;
    });
  };
});
